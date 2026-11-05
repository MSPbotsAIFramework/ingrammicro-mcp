from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Transport
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_port: int = 8080
    mcp_http_host: str = "0.0.0.0"

    # Auth mode:
    # "gateway" — production/SOP-compliant: credentials from HTTP headers per request (no global state)
    # "env"     — local dev only: shared credentials from env vars (not SOP-compliant)
    auth_mode: Literal["env", "gateway"] = "gateway"

    # Ingram Micro credentials (only required in env mode)
    ingrammicro_client_id: str | None = None
    ingrammicro_client_secret: str | None = None
    ingrammicro_customer_number: str | None = None
    ingrammicro_country_code: str | None = None

    # HTTP header names used to pass credentials in gateway mode.
    # The client must include all four headers on every /mcp request.
    ingrammicro_client_id_header: str = "X-IngramMicro-Client-Id"
    ingrammicro_client_secret_header: str = "X-IngramMicro-Client-Secret"
    ingrammicro_customer_number_header: str = "X-IngramMicro-Customer-Number"
    ingrammicro_country_code_header: str = "X-IngramMicro-Country-Code"

    # Identifies this integration to Ingram Micro as the calling system
    # (IM-SenderID header) — not tenant-specific credential material, so
    # it's a fixed setting rather than something each gateway request supplies.
    ingrammicro_sender_id: str = "MSPbots"

    # Ingram Micro's own sandbox/production distinction is a base-URL swap,
    # not a separate credential — override for sandbox testing.
    ingrammicro_base_url: str = "https://api.ingrammicro.com"

    # IM Cloud / CloudBlue Marketplace credentials (PRD-21595, env mode only).
    # A separate product from the Resellers API above: different auth
    # (direct API key, no OAuth2 exchange), different base URL, different
    # credential material.
    ingrammicro_cloud_api_key: str | None = None
    ingrammicro_cloud_customer_id: str | None = None

    ingrammicro_cloud_api_key_header: str = "X-IngramMicroCloud-Api-Key"
    ingrammicro_cloud_customer_id_header: str = "X-IngramMicroCloud-Customer-Id"

    # No hardcoded default, unlike ingrammicro_base_url above: the exact
    # IM Cloud API host is unverified (see docs/tickets/PRD-21595.md, Q1).
    # A client with no configured base URL returns a not_configured error
    # instead of silently calling a guessed host.
    ingrammicro_cloud_base_url: str | None = None

    # Per-request override for the above (PRD-21596): the Cloud Marketplace
    # base host is tenant/region-specific (confirmed via public Ingram
    # integration guides, same fact CloudMarketplaceProductsClient's own
    # per-request Base-Url header already relies on below) and cannot be
    # a single value for every reseller using this connector, so a caller
    # may send this header to override ingrammicro_cloud_base_url for just
    # that request. Optional -- absent means "use the env-configured
    # default", same fallback this setting already had before this header
    # existed; this is purely additive, not a behavior change for existing
    # callers that never send it.
    ingrammicro_cloud_base_url_header: str = "X-IngramMicroCloud-Base-Url"

    # IM Cloud Marketplace "Products" credentials (PRD-21597, env mode
    # only). A third, independent credential bundle within the same IM
    # Cloud / CloudBlue Marketplace product line as the two settings
    # above: different auth (Basic -> POST /token -> Bearer + a static
    # subscription-key header, verified against Ingram's own published
    # PDF — see cloud_api_client.py's module docstring), different
    # credential material, and (per that PDF) no customer/tenant id at
    # all — /products is a vendor-scoped catalog, not customer-scoped.
    # Base URL is also per-tenant here (not a shared default like
    # ingrammicro_base_url), same reasoning as ingrammicro_cloud_base_url
    # above: there is no single public constant for this host.
    ingrammicro_cloud_products_client_id: str | None = None
    ingrammicro_cloud_products_client_secret: str | None = None
    ingrammicro_cloud_products_marketplace: str | None = None
    ingrammicro_cloud_products_subscription_key: str | None = None
    ingrammicro_cloud_products_base_url: str | None = None

    ingrammicro_cloud_products_client_id_header: str = "X-IngramMicroCloud-Products-Client-Id"
    ingrammicro_cloud_products_client_secret_header: str = (
        "X-IngramMicroCloud-Products-Client-Secret"
    )
    ingrammicro_cloud_products_marketplace_header: str = "X-IngramMicroCloud-Products-Marketplace"
    ingrammicro_cloud_products_subscription_key_header: str = (
        "X-IngramMicroCloud-Products-Subscription-Key"
    )
    ingrammicro_cloud_products_base_url_header: str = "X-IngramMicroCloud-Products-Base-Url"

    @property
    def has_credentials(self) -> bool:
        """Returns True if the server can serve API calls.

        Gateway mode always returns True — each request carries its own credentials.
        Env mode requires all four Ingram Micro settings to be set.
        """
        if self.auth_mode == "gateway":
            return True
        return all(
            [
                self.ingrammicro_client_id,
                self.ingrammicro_client_secret,
                self.ingrammicro_customer_number,
                self.ingrammicro_country_code,
            ]
        )

    @property
    def has_cloud_credentials(self) -> bool:
        """Returns True if the server can serve Cloud Marketplace calls.

        Gateway mode always returns True — each request carries its own
        credentials (or omits them, in which case the tool itself returns
        a not_configured error; see server.get_cloud_client_from_context).
        Env mode requires both Cloud Marketplace settings and the base URL
        to be set.
        """
        if self.auth_mode == "gateway":
            return True
        return all(
            [
                self.ingrammicro_cloud_api_key,
                self.ingrammicro_cloud_customer_id,
                self.ingrammicro_cloud_base_url,
            ]
        )

    @property
    def has_cloud_products_credentials(self) -> bool:
        """Returns True if the server can serve Cloud Marketplace Products
        calls. Same env/gateway split as has_cloud_credentials above.
        """
        if self.auth_mode == "gateway":
            return True
        return all(
            [
                self.ingrammicro_cloud_products_client_id,
                self.ingrammicro_cloud_products_client_secret,
                self.ingrammicro_cloud_products_marketplace,
                self.ingrammicro_cloud_products_subscription_key,
                self.ingrammicro_cloud_products_base_url,
            ]
        )


def get_settings() -> Settings:
    return Settings()
