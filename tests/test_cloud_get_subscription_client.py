"""Request-shape and retry tests for CloudMarketplaceClient.get_subscription
(PRD-21596).

Mocks the actual httpx transport (via respx, same approach as
test_cloud_products_client.py) rather than the client itself, since what is
under test here is the real request shape (Bearer {api_key}, GET
/subscriptions/{id}, no customer_id query param) and the shared retry/
backoff policy from _http.py.

Test ids map to docs/tickets/PRD-21596.ac.json:
TC-IMC-001 -> test_get_subscription_returns_full_schema
TC-IMC-005 -> test_get_subscription_not_found_maps_to_structured_error
TC-IMC-006a -> test_get_subscription_retries_on_429_then_succeeds
TC-IMC-006b -> test_get_subscription_rate_limited_after_retries_exhausted
TC-IMC-008 -> test_get_subscription_uses_configured_base_url
TC-IMC-009 -> test_get_subscription_handles_missing_optional_fields
"""

import json

import httpx
import pytest
import respx

from ingrammicro_mcp.api_client import IngramMicroError
from ingrammicro_mcp.cloud_api_client import CloudMarketplaceClient

BASE_URL = "https://cloud.example.test"


@pytest.fixture(autouse=True)
def _no_retry_backoff_sleep(monkeypatch):
    # Same rationale as test_cloud_products_client.py: _request_with_retry
    # sleeps for real between 429/5xx retries; make it instant so the
    # retry-exhaustion test below doesn't spend real wall-clock time.
    import ingrammicro_mcp._http as _http_module

    async def _no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(_http_module.asyncio, "sleep", _no_sleep)


def _client(base_url: str = BASE_URL) -> CloudMarketplaceClient:
    return CloudMarketplaceClient(api_key="ck-abc123", customer_id="cust-42", base_url=base_url)


_SUBSCRIPTION = {
    "id": "1420038",
    "name": "Microsoft 365 Business Standard",
    "planId": "mpn-abc123",
    "status": "active",
    "products": [
        {"mpn": "CFQ7TTC0LH18", "name": "Microsoft 365 Business Standard", "quantity": 25, "unitPrice": 12.5, "currency": "USD"}
    ],
    "billingPeriod": {"type": "month", "duration": 1},
    "subscriptionPeriod": {"type": "year", "duration": 1},
    "renewalDate": "2027-03-01",
    "customerId": "1000001",
}


@pytest.mark.asyncio
@respx.mock
async def test_get_subscription_returns_full_schema():
    route = respx.get(f"{BASE_URL}/subscriptions/1420038").mock(
        return_value=httpx.Response(200, json=_SUBSCRIPTION)
    )

    result = await _client().get_subscription("1420038")

    for field in (
        "id", "name", "planId", "status", "products",
        "billingPeriod", "subscriptionPeriod", "renewalDate", "customerId",
    ):
        assert field in result, f"missing {field} in {result}"
    assert result["products"][0]["mpn"] == "CFQ7TTC0LH18"
    assert result["billingPeriod"] == {"type": "month", "duration": 1}
    assert result["subscriptionPeriod"] == {"type": "year", "duration": 1}

    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer ck-abc123"
    # No customer_id query param on the by-id lookup -- unlike list_subscriptions,
    # this is not a customer-scoped query (see cloud_api_client.py docstring).
    assert "customerId" not in dict(httpx.QueryParams(request.url.query))


@pytest.mark.asyncio
@respx.mock
async def test_get_subscription_not_found_maps_to_structured_error():
    respx.get(f"{BASE_URL}/subscriptions/does-not-exist").mock(
        return_value=httpx.Response(404, json={"message": "subscription not found"})
    )

    with pytest.raises(IngramMicroError) as exc_info:
        await _client().get_subscription("does-not-exist")

    assert exc_info.value.status_code == 404
    envelope = json.loads(exc_info.value.to_envelope())
    assert envelope["error"]["code"] == "not_found"
    assert envelope["error"]["retryable"] is False


@pytest.mark.asyncio
@respx.mock
async def test_get_subscription_retries_on_429_then_succeeds():
    route = respx.get(f"{BASE_URL}/subscriptions/1420038").mock(
        side_effect=[
            httpx.Response(429, json={"message": "rate limited"}),
            httpx.Response(200, json=_SUBSCRIPTION),
        ]
    )

    result = await _client().get_subscription("1420038")

    assert result["id"] == "1420038"
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_subscription_rate_limited_after_retries_exhausted():
    respx.get(f"{BASE_URL}/subscriptions/1420038").mock(
        return_value=httpx.Response(429, json={"message": "rate limited"})
    )

    with pytest.raises(IngramMicroError) as exc_info:
        await _client().get_subscription("1420038")

    assert exc_info.value.status_code == 429
    envelope = json.loads(exc_info.value.to_envelope())
    assert envelope["error"]["code"] == "rate_limited"
    assert envelope["error"]["retryable"] is True


@pytest.mark.asyncio
@respx.mock
async def test_get_subscription_uses_configured_base_url():
    override_base = "https://override.example.test/marketplace/eu"
    route = respx.get(f"{override_base}/subscriptions/1420038").mock(
        return_value=httpx.Response(200, json=_SUBSCRIPTION)
    )

    result = await _client(base_url=override_base).get_subscription("1420038")

    assert result["id"] == "1420038"
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_get_subscription_handles_missing_optional_fields():
    payload = dict(_SUBSCRIPTION)
    payload["renewalDate"] = None
    respx.get(f"{BASE_URL}/subscriptions/1420038").mock(return_value=httpx.Response(200, json=payload))

    result = await _client().get_subscription("1420038")

    assert result["renewalDate"] is None
    assert result["id"] == "1420038"
