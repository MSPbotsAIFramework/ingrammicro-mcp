"""Unit tests for ingrammicro_cloud_list_subscriptions (PRD-21595) and
ingrammicro_cloud_create_change_order (PRD-21598) -- both share the same
CloudMarketplaceClient / credential bundle, unlike the separate
ingrammicro_cloud_list_products client (see test_cloud_products_tool.py).

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

Test ids map to docs/tickets/PRD-21598.ac.json:
TC1->test_change_order_add_seats_returns_upstream_ack
TC2->test_change_order_remove_seats_uses_same_code_path
TC3->test_missing_subscription_id_is_invalid_argument,
     test_missing_products_is_invalid_argument,
     test_product_missing_mpn_or_quantity_is_invalid_argument,
     test_negative_quantity_is_invalid_argument
TC4->test_response_is_passthrough_ack_not_final_result
TC5->test_missing_cloud_credentials_returns_not_configured_without_http_call_change_order
TC6->test_upstream_5xx_returns_retryable_error_envelope_change_order,
     test_upstream_404_returns_non_retryable_error_envelope_change_order
TC7->test_change_order_tool_signature_has_no_customer_id_parameter,
     test_change_order_client_always_sources_customer_id_from_constructor
TC8->test_offer_attestation_parameters_passthrough_when_given,
     test_no_parameters_key_when_omitted
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


def _change_order_ack(**overrides) -> dict:
    base = {
        "id": "order-1",
        "type": "change",
        "customerId": "cust-42",
        "creationDate": "2026-11-05T00:00:00Z",
        "status": "submitted",
    }
    base.update(overrides)
    return base


class _StubCloudClient:
    """Records the call it received and returns/raises a canned result."""

    def __init__(self, result=None, error: IngramMicroError | None = None, customer_id: str = "cust-42"):
        self._result = result
        self._error = error
        self._customer_id = customer_id
        self.calls: list[dict] = []
        self.change_order_calls: list[dict] = []

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

    async def create_change_order(
        self,
        subscription_id,
        products,
        po_number=None,
        billing_period=None,
        subscription_period=None,
        total=None,
    ):
        self.change_order_calls.append(
            {
                "subscription_id": subscription_id,
                "products": products,
                "po_number": po_number,
                "billing_period": billing_period,
                "subscription_period": subscription_period,
                "total": total,
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


# ─── ingrammicro_cloud_create_change_order (PRD-21598) ──────────────────────


@pytest.mark.asyncio
async def test_change_order_add_seats_returns_upstream_ack():
    stub = _StubCloudClient(result=_change_order_ack())
    mcp = _server_with_stub(stub)

    text = await _call(
        mcp,
        "ingrammicro_cloud_create_change_order",
        {"subscription_id": "sub-1", "products": [{"mpn": "M365-E3", "quantity": 6}]},
    )

    envelope = json.loads(text)
    assert envelope == _change_order_ack()
    assert stub.change_order_calls == [
        {
            "subscription_id": "sub-1",
            "products": [{"mpn": "M365-E3", "quantity": 6}],
            "po_number": None,
            "billing_period": None,
            "subscription_period": None,
            "total": None,
        }
    ]


@pytest.mark.asyncio
async def test_change_order_remove_seats_uses_same_code_path():
    stub = _StubCloudClient(result=_change_order_ack())
    mcp = _server_with_stub(stub)

    text = await _call(
        mcp,
        "ingrammicro_cloud_create_change_order",
        {"subscription_id": "sub-1", "products": [{"mpn": "M365-E3", "quantity": 4}]},
    )

    envelope = json.loads(text)
    assert envelope == _change_order_ack()
    # Same stub method, same shape of call -- no separate "remove" branch.
    assert stub.change_order_calls[0]["products"] == [{"mpn": "M365-E3", "quantity": 4}]


@pytest.mark.asyncio
async def test_missing_subscription_id_is_invalid_argument():
    stub = _StubCloudClient(result=_change_order_ack())
    mcp = _server_with_stub(stub)

    text = await _call(
        mcp, "ingrammicro_cloud_create_change_order", {"products": [{"mpn": "M365-E3", "quantity": 6}]}
    )

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "invalid_argument"
    assert stub.change_order_calls == []


@pytest.mark.asyncio
async def test_missing_products_is_invalid_argument():
    stub = _StubCloudClient(result=_change_order_ack())
    mcp = _server_with_stub(stub)

    text = await _call(mcp, "ingrammicro_cloud_create_change_order", {"subscription_id": "sub-1"})

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "invalid_argument"
    assert stub.change_order_calls == []


@pytest.mark.asyncio
async def test_product_missing_mpn_or_quantity_is_invalid_argument():
    stub = _StubCloudClient(result=_change_order_ack())
    mcp = _server_with_stub(stub)

    missing_mpn = await _call(
        mcp,
        "ingrammicro_cloud_create_change_order",
        {"subscription_id": "sub-1", "products": [{"quantity": 6}]},
    )
    missing_quantity = await _call(
        mcp,
        "ingrammicro_cloud_create_change_order",
        {"subscription_id": "sub-1", "products": [{"mpn": "M365-E3"}]},
    )

    assert json.loads(missing_mpn)["error"]["code"] == "invalid_argument"
    assert json.loads(missing_quantity)["error"]["code"] == "invalid_argument"
    assert stub.change_order_calls == []


@pytest.mark.asyncio
async def test_negative_quantity_is_invalid_argument():
    stub = _StubCloudClient(result=_change_order_ack())
    mcp = _server_with_stub(stub)

    text = await _call(
        mcp,
        "ingrammicro_cloud_create_change_order",
        {"subscription_id": "sub-1", "products": [{"mpn": "M365-E3", "quantity": -1}]},
    )

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "invalid_argument"
    assert stub.change_order_calls == []


@pytest.mark.asyncio
async def test_response_is_passthrough_ack_not_final_result():
    stub = _StubCloudClient(result=_change_order_ack(status="processing"))
    mcp = _server_with_stub(stub)

    text = await _call(
        mcp,
        "ingrammicro_cloud_create_change_order",
        {"subscription_id": "sub-1", "products": [{"mpn": "M365-E3", "quantity": 6}]},
    )

    envelope = json.loads(text)
    # Exactly the upstream ack, no "completed" field synthesized or waited for.
    assert envelope["status"] == "processing"
    assert "completed" not in envelope
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "ingrammicro_cloud_create_change_order")
    doc = (tool.description or "").lower()
    assert "asynchronous" in doc or "not observable" in doc


@pytest.mark.asyncio
async def test_missing_cloud_credentials_returns_not_configured_without_http_call_change_order():
    mcp = _server_with_stub(None)

    text = await _call(
        mcp,
        "ingrammicro_cloud_create_change_order",
        {"subscription_id": "sub-1", "products": [{"mpn": "M365-E3", "quantity": 6}]},
    )

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "not_configured"
    assert "X-IngramMicroCloud-Api-Key" in envelope["error"]["message"]
    assert "X-IngramMicroCloud-Customer-Id" in envelope["error"]["message"]


@pytest.mark.asyncio
async def test_upstream_5xx_returns_retryable_error_envelope_change_order():
    stub = _StubCloudClient(error=IngramMicroError(503, "service unavailable"))
    mcp = _server_with_stub(stub)

    text = await _call(
        mcp,
        "ingrammicro_cloud_create_change_order",
        {"subscription_id": "sub-1", "products": [{"mpn": "M365-E3", "quantity": 6}]},
    )

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "upstream_error"
    assert envelope["error"]["retryable"] is True


@pytest.mark.asyncio
async def test_upstream_404_returns_non_retryable_error_envelope_change_order():
    stub = _StubCloudClient(error=IngramMicroError(404, "subscription not found"))
    mcp = _server_with_stub(stub)

    text = await _call(
        mcp,
        "ingrammicro_cloud_create_change_order",
        {"subscription_id": "sub-1", "products": [{"mpn": "M365-E3", "quantity": 6}]},
    )

    envelope = json.loads(text)
    assert envelope["error"]["code"] == "not_found"
    assert envelope["error"]["retryable"] is False


@pytest.mark.asyncio
async def test_change_order_tool_signature_has_no_customer_id_parameter():
    mcp = _server_with_stub(_StubCloudClient(result=_change_order_ack()))
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "ingrammicro_cloud_create_change_order")
    props = set(tool.inputSchema.get("properties", {}))
    assert "customer_id" not in props
    assert "customerId" not in props
    assert props == {
        "subscription_id",
        "products",
        "po_number",
        "billing_period",
        "subscription_period",
        "total",
    }


def test_change_order_client_always_sources_customer_id_from_constructor():
    client = CloudMarketplaceClient(api_key="k", customer_id="tenant-a-customer", base_url="https://x")
    import inspect

    sig = inspect.signature(client.create_change_order)
    assert "customer_id" not in sig.parameters
    assert "customerId" not in sig.parameters


@pytest.mark.asyncio
async def test_offer_attestation_parameters_passthrough_when_given():
    stub = _StubCloudClient(result=_change_order_ack())
    mcp = _server_with_stub(stub)

    attestation_params = [{"name": "offer_attestation", "structured_value": {"attestation_accepted": True}}]
    await _call(
        mcp,
        "ingrammicro_cloud_create_change_order",
        {
            "subscription_id": "sub-1",
            "products": [{"mpn": "M365-E3", "quantity": 6, "parameters": attestation_params}],
        },
    )

    assert stub.change_order_calls[0]["products"] == [
        {"mpn": "M365-E3", "quantity": 6, "parameters": attestation_params}
    ]


@pytest.mark.asyncio
async def test_no_parameters_key_when_omitted():
    stub = _StubCloudClient(result=_change_order_ack())
    mcp = _server_with_stub(stub)

    await _call(
        mcp,
        "ingrammicro_cloud_create_change_order",
        {"subscription_id": "sub-1", "products": [{"mpn": "M365-E3", "quantity": 6}]},
    )

    sent_product = stub.change_order_calls[0]["products"][0]
    assert "parameters" not in sent_product


def test_client_builds_request_body_with_subscription_id_per_product_and_optional_fields():
    """create_change_order places subscription_id inside each products[]
    item (Decision 1), merges customerId/type at the top level, and omits
    po_number/billing_period/subscription_period/total entirely when not
    given (never sends them as null)."""
    client = CloudMarketplaceClient(api_key="k", customer_id="cust-42", base_url="https://x")

    captured = {}

    async def _fake_request_with_retry(method, url, headers=None, params=None, json_body=None):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["json_body"] = json_body

        class _Resp:
            status_code = 200

            def json(self_inner):
                return _change_order_ack()

            content = b"{}"
            text = "{}"

        return _Resp()

    import ingrammicro_mcp.cloud_api_client as cloud_api_client

    original = cloud_api_client._request_with_retry
    cloud_api_client._request_with_retry = _fake_request_with_retry
    try:
        import asyncio

        asyncio.run(
            client.create_change_order(subscription_id="sub-1", products=[{"mpn": "M365-E3", "quantity": 6}])
        )
    finally:
        cloud_api_client._request_with_retry = original

    assert captured["method"] == "POST"
    assert captured["url"] == "https://x/orders"
    assert captured["headers"]["Authorization"] == "Bearer k"
    body = captured["json_body"]
    assert body["customerId"] == "cust-42"
    assert body["type"] == "change"
    assert body["products"] == [{"mpn": "M365-E3", "quantity": 6, "subscriptionId": "sub-1"}]
    assert "poNumber" not in body
    assert "billingPeriod" not in body
    assert "subscriptionPeriod" not in body
    assert "total" not in body
