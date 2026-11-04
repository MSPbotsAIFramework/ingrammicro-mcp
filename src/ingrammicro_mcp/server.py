import contextvars
import sys
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_client import IngramMicroClient
from .cloud_api_client import CloudMarketplaceClient, CloudMarketplaceProductsClient
from .config import Settings

# ─────────────────────────────────────────────────────────────────────────────
# Per-request credential contextvar for gateway mode.
# GatewayTokenMiddleware sets this before the MCP handler runs.
# Python asyncio copies context per task, so concurrent requests are isolated.
# Value is (client_id, client_secret, customer_number, country_code).
# ─────────────────────────────────────────────────────────────────────────────
_gateway_creds_var: contextvars.ContextVar[tuple[str, str, str, str] | None] = (
    contextvars.ContextVar("ingrammicro_gateway_creds", default=None)
)

# Same pattern, for the separate IM Cloud / CloudBlue Marketplace
# credentials (PRD-21595). Value is (api_key, customer_id). Unlike the
# four Resellers headers above, these are optional on the request as a
# whole — a caller that only wants the Resellers tools should not be
# forced to also send Cloud credentials (see GatewayTokenMiddleware).
_gateway_cloud_creds_var: contextvars.ContextVar[tuple[str, str] | None] = (
    contextvars.ContextVar("ingrammicro_gateway_cloud_creds", default=None)
)

# Same pattern again, for the IM Cloud Marketplace "Products" bundle
# (PRD-21597) — a third, independent credential set within the same IM
# Cloud / CloudBlue Marketplace product line as _gateway_cloud_creds_var
# above, but with different credential material and a verified-different
# auth scheme (see cloud_api_client.py's module docstring). Value is
# (client_id, client_secret, marketplace, subscription_key, base_url).
# Optional on the request as a whole, same reasoning as the Cloud bundle:
# a caller using only the Resellers tools (or only the Cloud Subscriptions
# tool) should not be forced to also send these.
_gateway_cloud_products_creds_var: contextvars.ContextVar[
    tuple[str, str, str, str, str] | None
] = contextvars.ContextVar("ingrammicro_gateway_cloud_products_creds", default=None)


def get_client_from_context(settings: Settings) -> IngramMicroClient | None:
    """Resolve the active IngramMicroClient for the current request context."""
    if settings.auth_mode == "gateway":
        creds = _gateway_creds_var.get()
        if creds is None:
            return None
        client_id, client_secret, customer_number, country_code = creds
    else:
        client_id = settings.ingrammicro_client_id
        client_secret = settings.ingrammicro_client_secret
        customer_number = settings.ingrammicro_customer_number
        country_code = settings.ingrammicro_country_code

    if not client_id or not client_secret or not customer_number or not country_code:
        return None
    return IngramMicroClient(
        client_id,
        client_secret,
        customer_number,
        country_code,
        settings.ingrammicro_sender_id,
        settings.ingrammicro_base_url,
    )


def get_cloud_client_from_context(settings: Settings) -> CloudMarketplaceClient | None:
    """Resolve the active CloudMarketplaceClient for the current request
    context. Returns None (-> tools/cloud.py's NO_CLOUD_TOKEN) if the Cloud
    headers/settings/base URL are not present — this is expected for any
    caller that only uses the Resellers tools.
    """
    if settings.auth_mode == "gateway":
        creds = _gateway_cloud_creds_var.get()
        if creds is None:
            return None
        api_key, customer_id = creds
    else:
        api_key = settings.ingrammicro_cloud_api_key
        customer_id = settings.ingrammicro_cloud_customer_id

    if not api_key or not customer_id or not settings.ingrammicro_cloud_base_url:
        return None
    return CloudMarketplaceClient(api_key, customer_id, settings.ingrammicro_cloud_base_url)


def get_cloud_products_client_from_context(
    settings: Settings,
) -> CloudMarketplaceProductsClient | None:
    """Resolve the active CloudMarketplaceProductsClient for the current
    request context (PRD-21597). Returns None (-> tools/cloud.py's
    NO_CLOUD_PRODUCTS_TOKEN) if the five Products headers/settings are not
    present — expected for any caller that only uses the Resellers tools
    or the (separate) Cloud Subscriptions tool.
    """
    if settings.auth_mode == "gateway":
        creds = _gateway_cloud_products_creds_var.get()
        if creds is None:
            return None
        client_id, client_secret, marketplace, subscription_key, base_url = creds
    else:
        client_id = settings.ingrammicro_cloud_products_client_id
        client_secret = settings.ingrammicro_cloud_products_client_secret
        marketplace = settings.ingrammicro_cloud_products_marketplace
        subscription_key = settings.ingrammicro_cloud_products_subscription_key
        base_url = settings.ingrammicro_cloud_products_base_url

    if not client_id or not client_secret or not marketplace or not subscription_key or not base_url:
        return None
    return CloudMarketplaceProductsClient(client_id, client_secret, marketplace, subscription_key, base_url)


class GatewayTokenMiddleware:
    """ASGI middleware for gateway mode.

    Reads the four configured credential headers from each request and
    stores them in the contextvar for the duration of that request. Returns
    401 if any is missing on /mcp requests.
    """

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        s = self.settings
        # Header lookup is case-insensitive in Starlette.
        client_id = request.headers.get(s.ingrammicro_client_id_header.lower())
        client_secret = request.headers.get(s.ingrammicro_client_secret_header.lower())
        customer_number = request.headers.get(s.ingrammicro_customer_number_header.lower())
        country_code = request.headers.get(s.ingrammicro_country_code_header.lower())
        required_headers = [
            s.ingrammicro_client_id_header,
            s.ingrammicro_client_secret_header,
            s.ingrammicro_customer_number_header,
            s.ingrammicro_country_code_header,
        ]
        if not client_id or not client_secret or not customer_number or not country_code:
            response = JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": f"Gateway mode requires the {', '.join(required_headers)} headers",
                    "required_headers": required_headers,
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        # Cloud Marketplace headers (PRD-21595) are read the same way, but
        # are NOT required on the request as a whole: a caller using only
        # the Resellers tools should not be forced to also send these.
        # Missing/incomplete Cloud headers just means
        # get_cloud_client_from_context() returns None, and
        # ingrammicro_cloud_list_subscriptions itself returns the
        # NO_CLOUD_TOKEN envelope (AC5) — no 401 here.
        cloud_api_key = request.headers.get(s.ingrammicro_cloud_api_key_header.lower())
        cloud_customer_id = request.headers.get(s.ingrammicro_cloud_customer_id_header.lower())
        cloud_token = None
        if cloud_api_key and cloud_customer_id:
            cloud_token = _gateway_cloud_creds_var.set((cloud_api_key, cloud_customer_id))

        # Cloud Marketplace Products headers (PRD-21597) — same "read the
        # same way, not required on the request as a whole" treatment as
        # the Cloud Subscriptions bundle just above. A partial bundle (1-4
        # of the 5 headers) is treated as absent, same as the Resellers
        # bundle's all-or-nothing check: get_cloud_products_client_from_context()
        # returns None either way, and ingrammicro_cloud_list_products
        # itself returns NO_CLOUD_PRODUCTS_TOKEN (AC4) — no 401 here.
        cloud_products_client_id = request.headers.get(
            s.ingrammicro_cloud_products_client_id_header.lower()
        )
        cloud_products_client_secret = request.headers.get(
            s.ingrammicro_cloud_products_client_secret_header.lower()
        )
        cloud_products_marketplace = request.headers.get(
            s.ingrammicro_cloud_products_marketplace_header.lower()
        )
        cloud_products_subscription_key = request.headers.get(
            s.ingrammicro_cloud_products_subscription_key_header.lower()
        )
        cloud_products_base_url = request.headers.get(
            s.ingrammicro_cloud_products_base_url_header.lower()
        )
        cloud_products_token = None
        if (
            cloud_products_client_id
            and cloud_products_client_secret
            and cloud_products_marketplace
            and cloud_products_subscription_key
            and cloud_products_base_url
        ):
            cloud_products_token = _gateway_cloud_products_creds_var.set(
                (
                    cloud_products_client_id,
                    cloud_products_client_secret,
                    cloud_products_marketplace,
                    cloud_products_subscription_key,
                    cloud_products_base_url,
                )
            )

        ctx_token = _gateway_creds_var.set(
            (client_id, client_secret, customer_number, country_code)
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _gateway_creds_var.reset(ctx_token)
            if cloud_token is not None:
                _gateway_cloud_creds_var.reset(cloud_token)
            if cloud_products_token is not None:
                _gateway_cloud_products_creds_var.reset(cloud_products_token)


def create_mcp_server(settings: Settings) -> FastMCP:
    """Build the FastMCP server instance and register all tools."""
    # DNS-rebinding protection is disabled because the container runs behind
    # mcp-gateway on an internal Docker network and is never publicly exposed.
    mcp = FastMCP(
        name="ingrammicro-mcp",
        instructions=(
            "Ingram Micro is a technology distributor — resellers buy hardware, "
            "software licenses, and cloud subscriptions through it to fulfill "
            "their own customers' orders. This server wraps the full non-"
            "webhook Ingram Micro Reseller API: product catalog/pricing, "
            "quotes, order placement/change/cancel/lookup, invoices, "
            "renewals, special-pricing deals, returns, and freight "
            "estimates — the single connector for Ingram Micro, no separate "
            "connector needed. Typical flow: ingrammicro_search_products -> "
            "ingrammicro_get_price_and_availability -> "
            "ingrammicro_create_order (stocked/direct-ship/licensing/warranty "
            "SKUs) or ingrammicro_create_cloud_order (cloud subscriptions, "
            "Quote-to-Order/Configure-to-Order — validate first with "
            "ingrammicro_validate_quote_to_order). ingrammicro_modify_order/"
            "ingrammicro_cancel_order only work in a narrow window before "
            "Ingram releases the order to its warehouse. Every order-"
            "placing/modifying call is real spend against the reseller's "
            "net-terms account — always confirm SKU, quantity, and price "
            "with a human before calling. ingrammicro_cloud_list_subscriptions "
            "is a separate capability for a different Ingram Micro product "
            "(the IM Cloud Marketplace, e.g. Microsoft 365 plans) — use it to "
            "find a subscription before adding/removing seats on it. "
            "ingrammicro_cloud_list_products looks up sellable Cloud "
            "Marketplace products by vendor code (e.g. find a Microsoft "
            "365 SKU mpn) — its own credential bundle, independent of "
            "the subscriptions tool's."
        ),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
        json_response=True,
    )

    client_factory: Callable[[], IngramMicroClient | None] = lambda: get_client_from_context(  # noqa: E731
        settings
    )
    cloud_client_factory: Callable[[], CloudMarketplaceClient | None] = lambda: get_cloud_client_from_context(  # noqa: E731
        settings
    )
    def cloud_products_client_factory() -> CloudMarketplaceProductsClient | None:
        return get_cloud_products_client_from_context(settings)

    if not settings.has_credentials:
        print(
            "Warning: No Ingram Micro credentials found. Tools will return "
            "not_configured errors until credentials are supplied.",
            file=sys.stderr,
        )
    if not settings.has_cloud_credentials:
        print(
            "Warning: No Ingram Micro Cloud Marketplace credentials found. "
            "ingrammicro_cloud_list_subscriptions will return not_configured "
            "errors until credentials are supplied.",
            file=sys.stderr,
        )
    if not settings.has_cloud_products_credentials:
        print(
            "Warning: No Ingram Micro Cloud Marketplace Products credentials "
            "found. ingrammicro_cloud_list_products will return "
            "not_configured errors until credentials are supplied.",
            file=sys.stderr,
        )

    from .tools import catalog, cloud, deals, freight, invoices, orders, quotes, renewals, returns

    catalog.register(mcp, client_factory)
    orders.register(mcp, client_factory)
    quotes.register(mcp, client_factory)
    invoices.register(mcp, client_factory)
    renewals.register(mcp, client_factory)
    deals.register(mcp, client_factory)
    returns.register(mcp, client_factory)
    freight.register(mcp, client_factory)
    cloud.register(mcp, cloud_client_factory, cloud_products_client_factory)

    return mcp
