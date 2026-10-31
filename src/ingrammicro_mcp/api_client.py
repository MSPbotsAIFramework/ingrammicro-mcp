import uuid
from typing import Any

import httpx

from ._http import _classify, _RequestFailed
from ._http import _request_with_retry as _shared_request_with_retry
from ._json import error_envelope


class IngramMicroError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Ingram Micro API error {status_code}: {message}")

    def to_envelope(self) -> str:
        code, retryable = _classify(self.status_code)
        return error_envelope(code, self.message, retryable)


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            detail = resp.json()
            if isinstance(detail, dict):
                # Ingram's error shape varies by layer: the OAuth/gateway
                # layer uses {"fault": {"faultstring": ...}}, the resellers
                # API itself uses {"message": ...}. Check both.
                fault = detail.get("fault")
                if isinstance(fault, dict) and fault.get("faultstring"):
                    msg = fault["faultstring"]
                else:
                    msg = detail.get("message") or str(detail)
            else:
                msg = str(detail)
        except ValueError:
            msg = resp.text
        raise IngramMicroError(resp.status_code, msg)


async def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    params: dict | None = None,
    json_body: Any = None,
) -> httpx.Response:
    """Resellers-specific wrapper around the shared retry helper
    (_http.py): translates a total network failure into an
    IngramMicroError(0, ...) so every existing call site here keeps seeing
    the same exception type it always has (no behavior change from the
    _http.py extraction).
    """
    try:
        return await _shared_request_with_retry(
            method, url, headers=headers, params=params, json_body=json_body
        )
    except _RequestFailed as e:
        raise IngramMicroError(0, e.message) from e


class IngramMicroClient:
    """Async httpx client wrapping the full non-webhook surface of the
    Ingram Micro Reseller API (Orders, Quote-to-Order, Catalog, Quotes,
    Invoices, Renewals, Deals, Returns, Freight Estimate), verified against
    Ingram Micro's own published OpenAPI spec
    (github.com/ingrammicro-xvantage/xi-sdk-openapispec, checked
    2026-09-01).

    Auth: OAuth2 client_credentials grant, but via `GET /oauth/oauth20/token`
    with client_id/client_secret as QUERY parameters (not the more common
    Basic-Auth-header form) — this is Ingram's own documented shape, not a
    guess. The token is short-lived; since this is a stateless multi-tenant
    service, it deliberately re-authenticates on every call rather than
    caching (same "re-login every call" pattern as `cisco-umbrella-mcp`/
    `covedataprotection-mcp`/`webroot-mcp`).

    Every real API call additionally requires three business-context
    headers Ingram calls out as mandatory on Orders/Q2O endpoints —
    IM-CustomerNumber, IM-CountryCode, IM-CorrelationID — plus an optional
    IM-SenderID. IM-CorrelationID must be unique per transaction per
    Ingram's own docs, so this client generates a fresh UUID for every
    call rather than exposing it as a tool parameter (an agent has no way
    to know it needs to be unique-per-call, and getting it wrong is not a
    meaningful choice for the agent to make).
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        customer_number: str,
        country_code: str,
        sender_id: str,
        base_url: str,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._customer_number = customer_number
        self._country_code = country_code
        self._sender_id = sender_id
        self._base_url = base_url.rstrip("/")

    async def _login(self) -> str:
        resp = await _request_with_retry(
            "GET",
            f"{self._base_url}/oauth/oauth20/token",
            headers={"Accept": "application/json"},
            params={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        _raise_for_status(resp)
        return resp.json()["access_token"]

    def _business_headers(self, token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "IM-CustomerNumber": self._customer_number,
            "IM-CountryCode": self._country_code,
            # Unique per transaction, per Ingram's own requirement — never
            # reused across calls or retries of the same logical call.
            "IM-CorrelationID": str(uuid.uuid4()),
        }
        if self._sender_id:
            # Ingram's own spec is inconsistent about the header name for
            # "who is calling": most endpoints document IM-SenderID, but
            # Invoices/Deals-details document IM-ApplicationID with an
            # identical description. Sending both is harmless and avoids
            # guessing which name a given endpoint actually validates.
            headers["IM-SenderID"] = self._sender_id
            headers["IM-ApplicationID"] = self._sender_id
        if extra:
            headers.update(extra)
        return headers

    def _clean_params(self, params: dict | None) -> dict:
        if not params:
            return {}
        return {k: v for k, v in params.items() if v is not None}

    async def get(
        self, path: str, params: dict | None = None, extra_headers: dict[str, str] | None = None
    ) -> Any:
        token = await self._login()
        resp = await _request_with_retry(
            "GET",
            f"{self._base_url}{path}",
            headers=self._business_headers(token, extra_headers),
            params=self._clean_params(params),
        )
        return self._handle(resp)

    async def post(
        self,
        path: str,
        json_body: Any = None,
        params: dict | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        token = await self._login()
        resp = await _request_with_retry(
            "POST",
            f"{self._base_url}{path}",
            headers=self._business_headers(token, extra_headers),
            params=self._clean_params(params),
            json_body=json_body,
        )
        return self._handle(resp)

    async def put(self, path: str, params: dict | None = None, json_body: Any = None) -> Any:
        token = await self._login()
        resp = await _request_with_retry(
            "PUT",
            f"{self._base_url}{path}",
            headers=self._business_headers(token),
            params=self._clean_params(params),
            json_body=json_body,
        )
        return self._handle(resp)

    async def delete(self, path: str, params: dict | None = None) -> Any:
        token = await self._login()
        resp = await _request_with_retry(
            "DELETE",
            f"{self._base_url}{path}",
            headers=self._business_headers(token),
            params=self._clean_params(params),
        )
        return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> Any:
        _raise_for_status(resp)
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return {"raw_response": resp.text}
