"""IM Cloud / CloudBlue Marketplace tool — read-only.

Added for PRD-21595. Separate from every other tool module in this repo:
those all wrap the Resellers API via IngramMicroClient; this one wraps the
distinct IM Cloud / CloudBlue Marketplace API via CloudMarketplaceClient.
See docs/tickets/PRD-21595.md for the design rationale.
"""

from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import IngramMicroError
from ..cloud_api_client import CloudMarketplaceClient

NO_CLOUD_TOKEN = error_envelope(
    "not_configured",
    "No Ingram Micro Cloud Marketplace credentials. Send the "
    "X-IngramMicroCloud-Api-Key and X-IngramMicroCloud-Customer-Id headers.",
    False,
)


def register(
    mcp: FastMCP, cloud_client_factory: Callable[[], CloudMarketplaceClient | None]
) -> None:

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
