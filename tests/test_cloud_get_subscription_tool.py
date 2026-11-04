"""Unit tests for ingrammicro_cloud_get_subscription (PRD-21596).

Mocks CloudMarketplaceClient directly (same approach as test_cloud_tools.py
for the sibling ingrammicro_cloud_list_subscriptions tool) -- the tool's own
branching (missing-credentials envelope, upstream-error envelope, response
passthrough) is what's under test here. No network calls; see
test_cloud_get_subscription_client.py for the real HTTP request-shape and
retry-policy assertions.

Test ids map to docs/tickets/PRD-21596.ac.json:
TC-IMC-002 -> (tools/list shape, covered by test_tools.py::test_tools_list_snapshot)
TC-IMC-003 -> test_missing_cloud_credentials_returns_not_configured_without_http_call
TC-IMC-004 -> (gateway-level, already covered by
               test_middleware.py::test_missing_cloud_headers_does_not_401_request_with_valid_resellers_headers
               -- this ticket adds no new header, so that existing proof still applies unchanged)
TC-IMC-007 -> test_get_subscription_has_no_tenant_identifying_parameter
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


def _subscription(**overrides) -> dict:
    base = {
        "id": "1420038",
        "name": "Microsoft 365 Business Standard",
        "planId": "mpn-abc123",
        "status": "active",
        "products": [{"mpn": "CFQ7TTC0LH18", "name": "Microsoft 365 Business Standard", "quantity": 25,
                      "unitPrice": 12.5, "currency": "USD"}],
        "billingPeriod": {"type": "month", "duration": 1},
        "subscriptionPeriod": {"type": "year", "duration": 1},
        "renewalDate": "2027-03-01",
        "customerId": "1000001",
    }
    base.update(overrides)
    return base


class _StubCloudClient:
    """Records the call it received and returns/raises a canned result."""

    def __init__(self, result=None, error: IngramMicroError | None = None):
        self._result = result
        self._error = error
        self.calls: list[str] = []

    async def get_subscription(self, subscription_id):
        self.calls.append(subscription_id)
        if self._error is not None:
            raise self._error
        return self._result

    async def list_subscriptions(self, **_kwargs):  # pragma: no cover - not exercised here
        raise NotImplementedError


def _server_with_stub(stub) -> FastMCP:
    mcp = FastMCP(name="test")
    cloud.register(mcp, lambda: stub)
    return mcp


@pytest.mark.asyncio
async def test_get_subscription_returns_client_payload_unmodified():
    stub = _StubCloudClient(result=_subscription())
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_get_subscription", {"subscription_id": "1420038"})

    payload = json.loads(text)
    for field in (
        "id", "name", "planId", "status", "products",
        "billingPeriod", "subscriptionPeriod", "renewalDate", "customerId",
    ):
        assert field in payload, f"missing {field} in {payload}"
    assert stub.calls == ["1420038"]


@pytest.mark.asyncio
async def test_missing_cloud_credentials_returns_not_configured_without_http_call():
    # client_factory returning None is exactly what get_cloud_client_from_context()
    # does when the Subscriptions-bundle headers are absent (server.py) --
    # no CloudMarketplaceClient is ever constructed, so there is no path to
    # an HTTP call in this scenario at all.
    mcp = _server_with_stub(None)

    text = await _call(mcp, "ingrammicro_cloud_get_subscription", {"subscription_id": "1420038"})

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "not_configured"
    assert "X-IngramMicroCloud-Api-Key" in envelope["error"]["message"]
    assert "X-IngramMicroCloud-Customer-Id" in envelope["error"]["message"]


@pytest.mark.asyncio
async def test_upstream_404_returns_non_retryable_error_envelope():
    stub = _StubCloudClient(error=IngramMicroError(404, "subscription not found"))
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_get_subscription", {"subscription_id": "does-not-exist"})

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "not_found"
    assert envelope["error"]["retryable"] is False


@pytest.mark.asyncio
async def test_upstream_5xx_returns_retryable_error_envelope():
    stub = _StubCloudClient(error=IngramMicroError(503, "service unavailable"))
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_get_subscription", {"subscription_id": "1420038"})

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "upstream_error"
    assert envelope["error"]["retryable"] is True


@pytest.mark.asyncio
async def test_get_subscription_handles_null_optional_field():
    stub = _StubCloudClient(result=_subscription(renewalDate=None))
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_get_subscription", {"subscription_id": "1420038"})

    payload = json.loads(text)
    assert payload["renewalDate"] is None
    assert payload["id"] == "1420038"


@pytest.mark.asyncio
async def test_get_subscription_has_no_tenant_identifying_parameter():
    # AC6 (multi-tenant isolation): the tool's only parameter is the
    # subscription id -- there is no customer_id/customerId argument a
    # caller (or a malicious tool-call) could use to ask this request's
    # credentials to act on a different tenant's data. The actual isolation
    # boundary (per-request contextvar, reset after each request) is tested
    # at the gateway level in test_middleware.py
    # (test_cloud_header_present_reaches_request_context_and_resets); this
    # test locks down the tool-signature half of that guarantee, mirroring
    # test_cloud_tools.py::test_tool_signature_has_no_customer_id_parameter
    # for the sibling list_subscriptions tool.
    mcp = _server_with_stub(_StubCloudClient(result=_subscription()))
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "ingrammicro_cloud_get_subscription")
    props = set(tool.inputSchema.get("properties", {}))
    assert "customer_id" not in props
    assert "customerId" not in props
    assert props == {"subscription_id"}
