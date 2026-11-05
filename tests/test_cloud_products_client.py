"""Auth-header-shape tests for CloudMarketplaceProductsClient (PRD-21597).

Mocks the actual httpx transport (via respx, already a dev dependency —
see pyproject.toml) rather than the client itself, since what is under
test here is exactly the detail a tool-level stub would hide: the real
request shape (Basic -> /token -> Bearer + X-Subscription-Key), verified
against Ingram Micro's own "Cloud Marketplace API.pdf" (see
cloud_api_client.py's module docstring for where/when that was fetched).

Test ids map to docs/tickets/PRD-21597.ac.json:
TC-CLOUD-001/002 -> test_list_products_sends_bearer_and_subscription_key_and_query_params,
                    test_list_products_omits_none_filters_from_query
TC-CLOUD-007     -> test_login_4xx_raises_ingram_micro_error,
                    test_products_call_5xx_raises_ingram_micro_error
(plus token-shape coverage the design's Data & API contract section specifies)
"""

import base64
import json

import httpx
import pytest
import respx

from ingrammicro_mcp.api_client import IngramMicroError
from ingrammicro_mcp.cloud_api_client import CloudMarketplaceProductsClient

BASE_URL = "https://cloud.example.test"


@pytest.fixture(autouse=True)
def _no_retry_backoff_sleep(monkeypatch):
    # _request_with_retry (_http.py) retries 429/5xx with a real
    # exponential-backoff sleep; make it instant here so the 5xx tests
    # below don't spend several real seconds waiting out retries that
    # this test isn't exercising the timing of.
    import ingrammicro_mcp._http as _http_module

    async def _no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(_http_module.asyncio, "sleep", _no_sleep)


def _client() -> CloudMarketplaceProductsClient:
    return CloudMarketplaceProductsClient(
        client_id="cid-123",
        client_secret="csecret-456",
        marketplace="us",
        subscription_key="subkey-789",
        base_url=BASE_URL,
    )


def _mock_token(status_code: int = 200, **json_body):
    return respx.post(f"{BASE_URL}/token").mock(
        return_value=httpx.Response(status_code, json=json_body or {"access_token": "tok-abc"})
    )


def _mock_products(status_code: int = 200, **json_body):
    return respx.get(f"{BASE_URL}/products").mock(
        return_value=httpx.Response(status_code, json=json_body or {"products": []})
    )


_PRODUCT = {
    "mpn": "AAA-12345",
    "name": "Microsoft 365 Business Standard",
    "vendor": "VA-888-104",
    "serviceName": "Microsoft 365",
    "billingPeriods": ["monthly", "annual"],
    "prices": [{"currency": "USD", "amount": 12.5}],
}


@pytest.mark.asyncio
@respx.mock
async def test_login_sends_basic_auth_subscription_key_and_json_body():
    token_route = _mock_token()
    products_route = _mock_products()

    await _client().list_products(vendor="VA-888-104")

    assert token_route.called
    token_request = token_route.calls[0].request
    expected_basic = base64.b64encode(b"cid-123:csecret-456").decode()
    assert token_request.headers["Authorization"] == f"Basic {expected_basic}"
    assert token_request.headers["X-Subscription-Key"] == "subkey-789"
    assert json.loads(token_request.content) == {"marketplace": "us"}

    assert products_route.called


@pytest.mark.asyncio
@respx.mock
async def test_list_products_sends_bearer_and_subscription_key_and_query_params():
    _mock_token()
    products_route = _mock_products(products=[_PRODUCT])

    result = await _client().list_products(
        vendor="VA-888-104",
        mpn="AAA-12345",
        name="Microsoft 365",
        service_name="Microsoft 365",
        limit=10,
        offset=0,
    )

    assert result["products"][0]["mpn"] == "AAA-12345"
    assert result["products"][0]["billingPeriods"] == ["monthly", "annual"]
    request = products_route.calls[0].request
    assert request.headers["Authorization"] == "Bearer tok-abc"
    assert request.headers["X-Subscription-Key"] == "subkey-789"
    params = dict(httpx.QueryParams(request.url.query))
    assert params == {
        "vendor": "VA-888-104",
        "mpn": "AAA-12345",
        "name": "Microsoft 365",
        "serviceName": "Microsoft 365",
        "limit": "10",
        "offset": "0",
    }


@pytest.mark.asyncio
@respx.mock
async def test_list_products_omits_none_filters_from_query():
    _mock_token()
    products_route = _mock_products()

    await _client().list_products(vendor="VA-888-104")

    request = products_route.calls[0].request
    params = dict(httpx.QueryParams(request.url.query))
    assert params == {"vendor": "VA-888-104"}


@pytest.mark.asyncio
@respx.mock
async def test_login_4xx_raises_ingram_micro_error_and_skips_products_call():
    _mock_token(401, message="invalid client credentials")
    products_route = _mock_products()

    with pytest.raises(IngramMicroError) as exc_info:
        await _client().list_products(vendor="VA-888-104")

    assert exc_info.value.status_code == 401
    assert "invalid client credentials" in exc_info.value.message
    assert not products_route.called


@pytest.mark.asyncio
@respx.mock
async def test_products_call_5xx_raises_ingram_micro_error():
    _mock_token()
    _mock_products(503, message="service unavailable")

    with pytest.raises(IngramMicroError) as exc_info:
        await _client().list_products(vendor="VA-888-104")

    assert exc_info.value.status_code == 503
    envelope = exc_info.value.to_envelope()
    assert json.loads(envelope)["error"]["code"] == "upstream_error"
    assert json.loads(envelope)["error"]["retryable"] is True


@pytest.mark.asyncio
@respx.mock
async def test_login_missing_access_token_raises_ingram_micro_error():
    _mock_token(not_a_token="oops")

    with pytest.raises(IngramMicroError) as exc_info:
        await _client().list_products(vendor="VA-888-104")

    assert "access_token" in exc_info.value.message
