"""Unit tests for ingrammicro_cloud_list_products (PRD-21597).

Mocks CloudMarketplaceProductsClient directly (same approach as
test_cloud_tools.py for the sibling ingrammicro_cloud_list_subscriptions
tool) -- the tool's own branching (missing-vendor guard, missing-
credentials envelope, upstream-error envelope, response passthrough) is
what's under test here. No network calls; see test_cloud_products_client.py
for the real HTTP request-shape assertions.

Test ids map to docs/tickets/PRD-21597.ac.json:
TC-CLOUD-001->test_list_products_returns_expected_fields_unmodified
TC-CLOUD-002->test_filters_are_passed_through_to_client
TC-CLOUD-003->test_missing_vendor_returns_invalid_argument_without_client_call
TC-CLOUD-004->test_missing_cloud_products_credentials_returns_not_configured_without_http_call
TC-CLOUD-005->(regression, covered by test_tools.py::test_tools_list_snapshot and
               test_cloud_tools.py's unmodified subscriptions tests)
TC-CLOUD-006->(gateway-level, covered in test_middleware.py)
TC-CLOUD-007->test_upstream_5xx_returns_retryable_error_envelope,
              test_upstream_404_returns_non_retryable_error_envelope
TC-CLOUD-008->(gateway-level isolation, covered in test_middleware.py)
"""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from ingrammicro_mcp.api_client import IngramMicroError
from ingrammicro_mcp.tools import cloud


async def _call(mcp: FastMCP, name: str, args: dict) -> str:
    result = await mcp.call_tool(name, args)
    content = result[0] if isinstance(result, tuple) else result
    item = content[0] if isinstance(content, list) else content
    return item.text


def _product(**overrides) -> dict:
    base = {
        "mpn": "AAA-12345",
        "name": "Microsoft 365 Business Standard",
        "vendor": "VA-888-104",
        "serviceName": "Microsoft 365",
        "billingPeriods": ["monthly", "annual"],
        "prices": [{"currency": "USD", "amount": 12.5}],
    }
    base.update(overrides)
    return base


class _StubProductsClient:
    """Records the call it received and returns/raises a canned result."""

    def __init__(self, result=None, error: IngramMicroError | None = None):
        self._result = result
        self._error = error
        self.calls: list[dict] = []

    async def list_products(self, vendor, mpn=None, name=None, service_name=None, limit=None, offset=None):
        self.calls.append(
            {
                "vendor": vendor,
                "mpn": mpn,
                "name": name,
                "service_name": service_name,
                "limit": limit,
                "offset": offset,
            }
        )
        if self._error is not None:
            raise self._error
        return self._result


def _server_with_stub(stub) -> FastMCP:
    mcp = FastMCP(name="test")
    # Pass a stub (or None) as the Subscriptions factory too -- irrelevant
    # to these tests, but register() requires it positionally.
    cloud.register(mcp, lambda: None, lambda: stub)
    return mcp


@pytest.mark.asyncio
async def test_list_products_returns_expected_fields_unmodified():
    stub = _StubProductsClient(result={"products": [_product()]})
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_list_products", {"vendor": "VA-888-104"})

    payload = json.loads(text)
    item = payload["products"][0]
    for field in ("mpn", "name", "vendor", "serviceName", "billingPeriods", "prices"):
        assert field in item, f"missing {field} in {item}"
    assert item["mpn"] == "AAA-12345"
    assert stub.calls == [
        {
            "vendor": "VA-888-104",
            "mpn": None,
            "name": None,
            "service_name": None,
            "limit": None,
            "offset": None,
        }
    ]


@pytest.mark.asyncio
async def test_filters_are_passed_through_to_client():
    stub = _StubProductsClient(result={"products": []})
    mcp = _server_with_stub(stub)

    await _call(
        mcp,
        "ingrammicro_cloud_list_products",
        {
            "vendor": "VA-888-104",
            "mpn": "AAA-12345",
            "name": "M365",
            "service_name": "Microsoft 365",
            "limit": 5,
            "offset": 10,
        },
    )

    assert stub.calls == [
        {
            "vendor": "VA-888-104",
            "mpn": "AAA-12345",
            "name": "M365",
            "service_name": "Microsoft 365",
            "limit": 5,
            "offset": 10,
        }
    ]


@pytest.mark.asyncio
async def test_empty_result_is_not_an_error():
    stub = _StubProductsClient(result={"products": []})
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_list_products", {"vendor": "VA-888-104"})

    assert json.loads(text) == {"products": []}


@pytest.mark.asyncio
async def test_missing_vendor_returns_invalid_argument_without_client_call():
    stub = _StubProductsClient(result={"products": [_product()]})
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_list_products", {})

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "invalid_argument"
    assert stub.calls == []


@pytest.mark.asyncio
async def test_missing_cloud_products_credentials_returns_not_configured_without_http_call():
    # products_client_factory returning None is exactly what
    # get_cloud_products_client_from_context() does when the five Cloud
    # Products headers are absent/incomplete (server.py) -- no
    # CloudMarketplaceProductsClient is ever constructed.
    mcp = _server_with_stub(None)

    text = await _call(mcp, "ingrammicro_cloud_list_products", {"vendor": "VA-888-104"})

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "not_configured"
    for header in (
        "X-IngramMicroCloud-Products-Client-Id",
        "X-IngramMicroCloud-Products-Client-Secret",
        "X-IngramMicroCloud-Products-Marketplace",
        "X-IngramMicroCloud-Products-Subscription-Key",
        "X-IngramMicroCloud-Products-Base-Url",
    ):
        assert header in envelope["error"]["message"]


@pytest.mark.asyncio
async def test_credentials_checked_before_vendor_argument():
    # Mirrors orders.py's ingrammicro_create_cloud_order precedent:
    # missing-credentials is checked before argument validation, so a
    # caller missing both gets the (more actionable) not_configured error.
    mcp = _server_with_stub(None)

    text = await _call(mcp, "ingrammicro_cloud_list_products", {})

    assert json.loads(text)["error"]["code"] == "not_configured"


@pytest.mark.asyncio
async def test_upstream_5xx_returns_retryable_error_envelope():
    stub = _StubProductsClient(error=IngramMicroError(503, "service unavailable"))
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_list_products", {"vendor": "VA-888-104"})

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "upstream_error"
    assert envelope["error"]["retryable"] is True


@pytest.mark.asyncio
async def test_upstream_404_returns_non_retryable_error_envelope():
    stub = _StubProductsClient(error=IngramMicroError(404, "vendor not found"))
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_list_products", {"vendor": "VA-888-104"})

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "not_found"
    assert envelope["error"]["retryable"] is False


@pytest.mark.asyncio
async def test_tool_registers_without_a_products_factory():
    # cloud.register()'s third argument is optional (test_cloud_tools.py's
    # existing calls only pass two args) -- confirm the tool still
    # registers and degrades to NO_CLOUD_PRODUCTS_TOKEN rather than
    # raising when no factory is supplied at all.
    mcp = FastMCP(name="test")
    cloud.register(mcp, lambda: None)

    text = await _call(mcp, "ingrammicro_cloud_list_products", {"vendor": "VA-888-104"})

    assert json.loads(text)["error"]["code"] == "not_configured"
