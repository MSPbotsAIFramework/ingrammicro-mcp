"""Unit tests for ingrammicro_cloud_list_subscriptions (PRD-21595).

Mocks CloudMarketplaceClient directly (same approach as test_tools.py's
test_create_cloud_order_rejects_neither_quote_nor_lines) rather than
mocking httpx — the tool's own branching (missing-credentials envelope,
upstream-error envelope, response passthrough) is what's under test here.
No network calls.

Test ids map to docs/tickets/PRD-21595.ac.json:
TC1->test_list_subscriptions_active_filter_returns_expected_fields
TC2->test_list_subscriptions_no_status_filter_is_not_defaulted
TC3->test_list_subscriptions_empty_result_is_not_an_error
TC4->test_list_subscriptions_passes_creation_date_range_params
TC5->test_missing_cloud_credentials_returns_not_configured_without_http_call
TC6->test_upstream_5xx_returns_retryable_error_envelope,
     test_upstream_404_returns_non_retryable_error_envelope
TC7->test_tool_signature_has_no_customer_id_parameter,
     test_client_always_sources_customer_id_from_constructor_not_call_args
"""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from ingrammicro_mcp.api_client import IngramMicroError
from ingrammicro_mcp.cloud_api_client import CloudMarketplaceClient
from ingrammicro_mcp.tools import cloud


async def _call(mcp: FastMCP, name: str, args: dict) -> str:
    result = await mcp.call_tool(name, args)
    content = result[0] if isinstance(result, tuple) else result
    item = content[0] if isinstance(content, list) else content
    return item.text


def _subscription(**overrides) -> dict:
    base = {
        "id": "sub-1",
        "status": "active",
        "customerId": "cust-42",
        "renewalDate": "2027-01-01",
        "totalPrice": {"currency": "USD", "amount": 100},
        "products": [{"mpn": "M365-E3", "quantity": 5, "unitPrice": 20}],
    }
    base.update(overrides)
    return base


class _StubCloudClient:
    """Records the call it received and returns/raises a canned result."""

    def __init__(self, result=None, error: IngramMicroError | None = None):
        self._result = result
        self._error = error
        self.calls: list[dict] = []

    async def list_subscriptions(self, status=None, creation_date_from=None, creation_date_to=None):
        self.calls.append(
            {
                "status": status,
                "creation_date_from": creation_date_from,
                "creation_date_to": creation_date_to,
            }
        )
        if self._error is not None:
            raise self._error
        return self._result


def _server_with_stub(stub) -> FastMCP:
    mcp = FastMCP(name="test")
    cloud.register(mcp, lambda: stub)
    return mcp


@pytest.mark.asyncio
async def test_list_subscriptions_active_filter_returns_expected_fields():
    stub = _StubCloudClient(result=[_subscription(status="active")])
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_list_subscriptions", {"status": "active"})

    items = json.loads(text)
    assert len(items) == 1
    item = items[0]
    for field in ("id", "status", "customerId", "renewalDate", "totalPrice", "products"):
        assert field in item, f"missing {field} in {item}"
    assert item["status"] == "active"
    assert item["products"][0]["mpn"] == "M365-E3"
    assert stub.calls == [{"status": "active", "creation_date_from": None, "creation_date_to": None}]


@pytest.mark.asyncio
async def test_list_subscriptions_no_status_filter_is_not_defaulted():
    stub = _StubCloudClient(result=[_subscription(status="active"), _subscription(id="sub-2", status="hold")])
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_list_subscriptions", {})

    items = json.loads(text)
    assert {i["status"] for i in items} == {"active", "hold"}
    # the tool must not inject a default status -- the client receives None
    assert stub.calls == [{"status": None, "creation_date_from": None, "creation_date_to": None}]


@pytest.mark.asyncio
async def test_list_subscriptions_empty_result_is_not_an_error():
    stub = _StubCloudClient(result=[])
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_list_subscriptions", {})

    assert json.loads(text) == []


@pytest.mark.asyncio
async def test_list_subscriptions_passes_creation_date_range_params():
    stub = _StubCloudClient(result=[])
    mcp = _server_with_stub(stub)

    await _call(
        mcp,
        "ingrammicro_cloud_list_subscriptions",
        {"creation_date_from": "2026-01-01", "creation_date_to": "2026-06-30"},
    )

    assert stub.calls == [
        {"status": None, "creation_date_from": "2026-01-01", "creation_date_to": "2026-06-30"}
    ]


@pytest.mark.asyncio
async def test_missing_cloud_credentials_returns_not_configured_without_http_call():
    # client_factory returning None is exactly what
    # get_cloud_client_from_context() does when the two Cloud headers are
    # absent (server.py) -- no CloudMarketplaceClient is ever constructed,
    # so there is no path to an HTTP call in this scenario at all.
    mcp = _server_with_stub(None)

    text = await _call(mcp, "ingrammicro_cloud_list_subscriptions", {})

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "not_configured"
    assert "X-IngramMicroCloud-Api-Key" in envelope["error"]["message"]
    assert "X-IngramMicroCloud-Customer-Id" in envelope["error"]["message"]


@pytest.mark.asyncio
async def test_upstream_5xx_returns_retryable_error_envelope():
    stub = _StubCloudClient(error=IngramMicroError(503, "service unavailable"))
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_list_subscriptions", {})

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "upstream_error"
    assert envelope["error"]["retryable"] is True


@pytest.mark.asyncio
async def test_upstream_404_returns_non_retryable_error_envelope():
    stub = _StubCloudClient(error=IngramMicroError(404, "customer not found"))
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_list_subscriptions", {})

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "not_found"
    assert envelope["error"]["retryable"] is False


@pytest.mark.asyncio
async def test_tool_signature_has_no_customer_id_parameter():
    mcp = _server_with_stub(_StubCloudClient(result=[]))
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "ingrammicro_cloud_list_subscriptions")
    props = set(tool.inputSchema.get("properties", {}))
    assert "customer_id" not in props
    assert "customerId" not in props
    assert props == {"status", "creation_date_from", "creation_date_to"}


def test_client_always_sources_customer_id_from_constructor_not_call_args():
    client = CloudMarketplaceClient(api_key="k", customer_id="tenant-a-customer", base_url="https://x")
    assert client._customer_id == "tenant-a-customer"
    # list_subscriptions has no customer_id/customerId parameter at all --
    # a caller (or a malicious tool-call argument) has no way to pass one in.
    import inspect

    sig = inspect.signature(client.list_subscriptions)
    assert "customer_id" not in sig.parameters
    assert "customerId" not in sig.parameters
