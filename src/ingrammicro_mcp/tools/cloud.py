"""IM Cloud / CloudBlue Marketplace tools — read-only.

Added for PRD-21595 (ingrammicro_cloud_list_subscriptions) and extended
for PRD-21597 (ingrammicro_cloud_list_products). Separate from every other
tool module in this repo: those all wrap the Resellers API via
IngramMicroClient; this one wraps the distinct IM Cloud / CloudBlue
Marketplace product line — itself split across two independent client
classes with two different, separately-verified auth schemes (see
cloud_api_client.py's module docstring). See docs/tickets/PRD-21595.md
and docs/tickets/PRD-21597.md for the design rationale for each tool.
"""

from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import IngramMicroError
from ..cloud_api_client import CloudMarketplaceClient, CloudMarketplaceProductsClient

NO_CLOUD_TOKEN = error_envelope(
    "not_configured",
    "No Ingram Micro Cloud Marketplace credentials. Send the "
    "X-IngramMicroCloud-Api-Key and X-IngramMicroCloud-Customer-Id headers.",
    False,
)

NO_CLOUD_PRODUCTS_TOKEN = error_envelope(
    "not_configured",
    "No Ingram Micro Cloud Marketplace Products credentials. Send the "
    "X-IngramMicroCloud-Products-Client-Id, "
    "X-IngramMicroCloud-Products-Client-Secret, "
    "X-IngramMicroCloud-Products-Marketplace, "
    "X-IngramMicroCloud-Products-Subscription-Key, and "
    "X-IngramMicroCloud-Products-Base-Url headers.",
    False,
)

_NO_CLOUD_PRODUCTS_CLIENT: Callable[[], CloudMarketplaceProductsClient | None] = lambda: None  # noqa: E731


def register(
    mcp: FastMCP,
    cloud_client_factory: Callable[[], CloudMarketplaceClient | None],
    cloud_products_client_factory: Callable[[], CloudMarketplaceProductsClient | None] | None = None,
) -> None:
    products_factory = cloud_products_client_factory or _NO_CLOUD_PRODUCTS_CLIENT

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_cloud_list_subscriptions(
        status: Annotated[
            str | None,
            Field(
                description='Filter by subscription status: "pending", "active", "hold", '
                '"terminated", or "removed". Omit to return subscriptions in any status.'
            ),
        ] = None,
        creation_date_from: Annotated[
            str | None, Field(description="Only return subscriptions created on/after this ISO 8601 date.")
        ] = None,
        creation_date_to: Annotated[
            str | None, Field(description="Only return subscriptions created on/before this ISO 8601 date.")
        ] = None,
    ) -> str:
        """List this customer's Ingram Micro Cloud Marketplace subscriptions
        (e.g. Microsoft 365 plans). Use this to find the subscription to add
        or remove seats on before changing a license count. The customer is
        the one bound to this connection's credentials — there is no
        customer id parameter.
        """
        client = cloud_client_factory()
        if client is None:
            return NO_CLOUD_TOKEN
        try:
            result = await client.list_subscriptions(
                status=status,
                creation_date_from=creation_date_from,
                creation_date_to=creation_date_to,
            )
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_cloud_list_products(
        vendor: Annotated[
            str | None,
            Field(
                description="Vendor code to list sellable Cloud Marketplace products for "
                '(e.g. "VA-888-104" for Microsoft). Required — enforced in the tool body '
                "(see ingrammicro_create_cloud_order for the same pattern) rather than via "
                "JSON-Schema required, so a missing value returns a structured error "
                "instead of a protocol-level rejection."
            ),
        ] = None,
        mpn: Annotated[
            str | None, Field(description="Filter to a specific manufacturer part number.")
        ] = None,
        name: Annotated[
            str | None, Field(description="Filter by product name (vendor-defined matching).")
        ] = None,
        service_name: Annotated[
            str | None, Field(description="Filter by the vendor's service/product-family name.")
        ] = None,
        limit: Annotated[int | None, Field(description="Max results to return (pagination).")] = None,
        offset: Annotated[int | None, Field(description="Result offset to start from (pagination).")] = None,
    ) -> str:
        """Look up sellable Ingram Micro Cloud Marketplace products by
        vendor code — e.g. find the Microsoft 365 SKU mpn/name to quote.
        Uses a separate credential bundle from
        ingrammicro_cloud_list_subscriptions (the two IM Cloud Marketplace
        tools are independent; neither requires the other's credentials).
        """
        client = products_factory()
        if client is None:
            return NO_CLOUD_PRODUCTS_TOKEN
        if not vendor:
            return error_envelope(
                "invalid_argument",
                "vendor is required (the vendor/manufacturer code to list products for, "
                'e.g. "VA-888-104" for Microsoft) — none was given.',
                False,
            )
        try:
            result = await client.list_products(
                vendor=vendor,
                mpn=mpn,
                name=name,
                service_name=service_name,
                limit=limit,
                offset=offset,
            )
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()
