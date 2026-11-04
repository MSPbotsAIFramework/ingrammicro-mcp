"""Gateway credential middleware tests: missing-header 401, and header
values correctly reaching the per-request contextvar (no global-state
leakage across requests).
"""

from starlette.testclient import TestClient

from ingrammicro_mcp.__main__ import _build_http_app
from ingrammicro_mcp.config import Settings
from ingrammicro_mcp.server import create_mcp_server, get_client_from_context


def _make_app():
    settings = Settings()
    mcp = create_mcp_server(settings)
    return _build_http_app(mcp, settings), settings


def test_health_is_local_and_does_not_require_credentials():
    app, _ = _make_app()
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_missing_header_returns_401_with_required_headers_listed():
    app, _ = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert resp.status_code == 401
        body = resp.json()
        for h in [
            "X-IngramMicro-Client-Id",
            "X-IngramMicro-Client-Secret",
            "X-IngramMicro-Customer-Number",
            "X-IngramMicro-Country-Code",
        ]:
            assert h in body["required_headers"]


def test_only_some_of_four_required_headers_still_401():
    app, _ = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={
                "Accept": "application/json, text/event-stream",
                "X-IngramMicro-Client-Id": "id",
                "X-IngramMicro-Client-Secret": "secret",
            },
        )
        assert resp.status_code == 401


def test_header_present_reaches_request_context():
    # Directly exercises the middleware's contextvar plumbing without a full
    # MCP protocol round-trip: confirms the header values that arrive on the
    # request are exactly what get_client_from_context sees, and that they're
    # reset afterward (no leakage to the next request).
    import asyncio

    from ingrammicro_mcp.server import GatewayTokenMiddleware, _gateway_creds_var

    settings = Settings()
    seen = {}

    async def fake_app(scope, receive, send):
        seen["creds"] = _gateway_creds_var.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayTokenMiddleware(fake_app, settings)

    async def run():
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [
                (b"x-ingrammicro-client-id", b"id-123"),
                (b"x-ingrammicro-client-secret", b"secret-456"),
                (b"x-ingrammicro-customer-number", b"20-222222"),
                (b"x-ingrammicro-country-code", b"US"),
            ],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

    asyncio.run(run())
    assert seen["creds"] == ("id-123", "secret-456", "20-222222", "US")
    # After the request completes, the contextvar must be reset — a fresh
    # get() outside any request context sees no leftover credential.
    assert _gateway_creds_var.get() is None


def test_client_factory_returns_none_without_context():
    settings = Settings()
    assert get_client_from_context(settings) is None


def test_missing_cloud_headers_does_not_401_request_with_valid_resellers_headers():
    # PRD-21595: the two X-IngramMicroCloud-* headers are optional on the
    # request as a whole -- a caller using only the Resellers tools must
    # not be forced to also send them. Only the four Resellers headers can
    # cause a 401 here; Cloud credential absence is handled entirely inside
    # ingrammicro_cloud_list_subscriptions (NO_CLOUD_TOKEN envelope).
    app, _ = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={
                "Accept": "application/json, text/event-stream",
                "X-IngramMicro-Client-Id": "id",
                "X-IngramMicro-Client-Secret": "secret",
                "X-IngramMicro-Customer-Number": "20-222222",
                "X-IngramMicro-Country-Code": "US",
            },
        )
        assert resp.status_code != 401


def test_cloud_header_present_reaches_request_context_and_resets():
    # Same shape as test_header_present_reaches_request_context above, for
    # the separate Cloud contextvar.
    import asyncio

    from ingrammicro_mcp.server import GatewayTokenMiddleware, _gateway_cloud_creds_var

    settings = Settings()
    seen = {}

    async def fake_app(scope, receive, send):
        seen["cloud_creds"] = _gateway_cloud_creds_var.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayTokenMiddleware(fake_app, settings)

    async def run():
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [
                (b"x-ingrammicro-client-id", b"id-123"),
                (b"x-ingrammicro-client-secret", b"secret-456"),
                (b"x-ingrammicro-customer-number", b"20-222222"),
                (b"x-ingrammicro-country-code", b"US"),
                (b"x-ingrammicrocloud-api-key", b"cloud-key-789"),
                (b"x-ingrammicrocloud-customer-id", b"cust-42"),
            ],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

    asyncio.run(run())
    assert seen["cloud_creds"] == ("cloud-key-789", "cust-42")
    assert _gateway_cloud_creds_var.get() is None


def test_cloud_headers_absent_leaves_cloud_context_none():
    import asyncio

    from ingrammicro_mcp.server import GatewayTokenMiddleware, _gateway_cloud_creds_var

    settings = Settings()
    seen = {}

    async def fake_app(scope, receive, send):
        seen["cloud_creds"] = _gateway_cloud_creds_var.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayTokenMiddleware(fake_app, settings)

    async def run():
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [
                (b"x-ingrammicro-client-id", b"id-123"),
                (b"x-ingrammicro-client-secret", b"secret-456"),
                (b"x-ingrammicro-customer-number", b"20-222222"),
                (b"x-ingrammicro-country-code", b"US"),
            ],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

    asyncio.run(run())
    assert seen["cloud_creds"] is None


def test_cloud_client_factory_returns_none_without_context():
    from ingrammicro_mcp.server import get_cloud_client_from_context

    settings = Settings()
    assert get_cloud_client_from_context(settings) is None


# ─────────────────────────────────────────────────────────────────────────
# Cloud Marketplace Products bundle (PRD-21597) -- same shape as the Cloud
# Subscriptions bundle tests above, for the third, independent contextvar.
# ─────────────────────────────────────────────────────────────────────────


def test_missing_cloud_products_headers_does_not_401_request_with_valid_resellers_headers():
    # Same reasoning as test_missing_cloud_headers_does_not_401... above:
    # the five Products headers are optional on the request as a whole.
    app, _ = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={
                "Accept": "application/json, text/event-stream",
                "X-IngramMicro-Client-Id": "id",
                "X-IngramMicro-Client-Secret": "secret",
                "X-IngramMicro-Customer-Number": "20-222222",
                "X-IngramMicro-Country-Code": "US",
            },
        )
        assert resp.status_code != 401


def test_cloud_products_header_present_reaches_request_context_and_resets():
    import asyncio

    from ingrammicro_mcp.server import GatewayTokenMiddleware, _gateway_cloud_products_creds_var

    settings = Settings()
    seen = {}

    async def fake_app(scope, receive, send):
        seen["cloud_products_creds"] = _gateway_cloud_products_creds_var.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayTokenMiddleware(fake_app, settings)

    async def run():
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [
                (b"x-ingrammicro-client-id", b"id-123"),
                (b"x-ingrammicro-client-secret", b"secret-456"),
                (b"x-ingrammicro-customer-number", b"20-222222"),
                (b"x-ingrammicro-country-code", b"US"),
                (b"x-ingrammicrocloud-products-client-id", b"pid-123"),
                (b"x-ingrammicrocloud-products-client-secret", b"psecret-456"),
                (b"x-ingrammicrocloud-products-marketplace", b"us"),
                (b"x-ingrammicrocloud-products-subscription-key", b"subkey-789"),
                (b"x-ingrammicrocloud-products-base-url", b"https://cloud.example.test"),
            ],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

    asyncio.run(run())
    assert seen["cloud_products_creds"] == (
        "pid-123",
        "psecret-456",
        "us",
        "subkey-789",
        "https://cloud.example.test",
    )
    # After the request completes, the contextvar must be reset.
    assert _gateway_cloud_products_creds_var.get() is None


def test_cloud_products_headers_absent_leaves_context_none():
    import asyncio

    from ingrammicro_mcp.server import GatewayTokenMiddleware, _gateway_cloud_products_creds_var

    settings = Settings()
    seen = {}

    async def fake_app(scope, receive, send):
        seen["cloud_products_creds"] = _gateway_cloud_products_creds_var.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayTokenMiddleware(fake_app, settings)

    async def run():
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [
                (b"x-ingrammicro-client-id", b"id-123"),
                (b"x-ingrammicro-client-secret", b"secret-456"),
                (b"x-ingrammicro-customer-number", b"20-222222"),
                (b"x-ingrammicro-country-code", b"US"),
            ],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

    asyncio.run(run())
    assert seen["cloud_products_creds"] is None


def test_partial_cloud_products_bundle_leaves_context_none():
    # Four of the five Products headers present (missing Base-Url): not
    # treated as present, same all-or-nothing rule as the four Resellers
    # headers and the two Cloud Subscriptions headers.
    import asyncio

    from ingrammicro_mcp.server import GatewayTokenMiddleware, _gateway_cloud_products_creds_var

    settings = Settings()
    seen = {}

    async def fake_app(scope, receive, send):
        seen["cloud_products_creds"] = _gateway_cloud_products_creds_var.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayTokenMiddleware(fake_app, settings)

    async def run():
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [
                (b"x-ingrammicro-client-id", b"id-123"),
                (b"x-ingrammicro-client-secret", b"secret-456"),
                (b"x-ingrammicro-customer-number", b"20-222222"),
                (b"x-ingrammicro-country-code", b"US"),
                (b"x-ingrammicrocloud-products-client-id", b"pid-123"),
                (b"x-ingrammicrocloud-products-client-secret", b"psecret-456"),
                (b"x-ingrammicrocloud-products-marketplace", b"us"),
                (b"x-ingrammicrocloud-products-subscription-key", b"subkey-789"),
                # Base-Url intentionally omitted.
            ],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

    asyncio.run(run())
    assert seen["cloud_products_creds"] is None


def test_cloud_products_client_factory_returns_none_without_context():
    from ingrammicro_mcp.server import get_cloud_products_client_from_context

    settings = Settings()
    assert get_cloud_products_client_from_context(settings) is None


def test_two_cloud_bundles_isolated_in_the_same_request():
    # AC7 at the gateway boundary: a request carrying both the Cloud
    # Subscriptions bundle and the Cloud Products bundle gets both
    # contextvars set independently -- neither leaks into or clobbers the
    # other.
    import asyncio

    from ingrammicro_mcp.server import (
        GatewayTokenMiddleware,
        _gateway_cloud_creds_var,
        _gateway_cloud_products_creds_var,
    )

    settings = Settings()
    seen = {}

    async def fake_app(scope, receive, send):
        seen["cloud_creds"] = _gateway_cloud_creds_var.get()
        seen["cloud_products_creds"] = _gateway_cloud_products_creds_var.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayTokenMiddleware(fake_app, settings)

    async def run():
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [
                (b"x-ingrammicro-client-id", b"id-123"),
                (b"x-ingrammicro-client-secret", b"secret-456"),
                (b"x-ingrammicro-customer-number", b"20-222222"),
                (b"x-ingrammicro-country-code", b"US"),
                (b"x-ingrammicrocloud-api-key", b"cloud-key-789"),
                (b"x-ingrammicrocloud-customer-id", b"cust-42"),
                (b"x-ingrammicrocloud-products-client-id", b"pid-123"),
                (b"x-ingrammicrocloud-products-client-secret", b"psecret-456"),
                (b"x-ingrammicrocloud-products-marketplace", b"us"),
                (b"x-ingrammicrocloud-products-subscription-key", b"subkey-789"),
                (b"x-ingrammicrocloud-products-base-url", b"https://cloud.example.test"),
            ],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

    asyncio.run(run())
    assert seen["cloud_creds"] == ("cloud-key-789", "cust-42")
    assert seen["cloud_products_creds"] == (
        "pid-123",
        "psecret-456",
        "us",
        "subkey-789",
        "https://cloud.example.test",
    )
    assert _gateway_cloud_creds_var.get() is None
    assert _gateway_cloud_products_creds_var.get() is None
