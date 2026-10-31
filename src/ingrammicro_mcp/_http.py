"""Shared HTTP-with-retry plumbing, used by every upstream client in this
repo (Resellers API, IM Cloud / CloudBlue Marketplace API, ...).

Extracted out of api_client.py (PRD-21595) so a second client does not
duplicate the retry/backoff/connection-pool logic. No behavior change for
the existing Resellers client.
"""

import asyncio
from typing import Any

import httpx

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_MAX_BACKOFF_SECONDS = 20.0

# One shared connection pool for the process lifetime. No credentials are
# ever stored on it — every client passes its own credentials per-call, so
# sharing this pool across tenants/requests is safe (see server.py's
# contextvar-based credential isolation, which is what actually keeps
# tenants apart).
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
    return _http_client


# status_code -> (error code, retryable). status_code 0 means a network/
# connection-level failure (no response at all).
_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    0: ("upstream_error", True),
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    422: ("invalid_argument", False),
    429: ("rate_limited", True),
}


def _classify(status_code: int) -> tuple[str, bool]:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if status_code >= 500:
        return "upstream_error", True
    return "invalid_argument", False


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), _MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    return min(2**attempt, _MAX_BACKOFF_SECONDS)


class _RequestFailed(Exception):
    """Internal signal for a request that exhausted retries with no
    response at all (network/connection-level failure). Callers translate
    this into their own vendor-specific error type.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    params: dict | None = None,
    json_body: Any = None,
) -> httpx.Response:
    """Issue one HTTP request against the shared connection pool, with
    limited retry + exponential backoff on 429/5xx and network-level
    errors (honoring Retry-After when the upstream sends one). Raises
    _RequestFailed (never returns) if every attempt fails at the network
    level; callers wrap that into their own vendor-specific exception.
    """
    client = _get_http_client()
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.request(
                method, url, headers=headers, params=params, json=json_body
            )
        except httpx.RequestError as e:
            last_exc = e
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(min(2**attempt, _MAX_BACKOFF_SECONDS))
                continue
            raise _RequestFailed(f"{e or type(e).__name__} (url={url})") from e

        if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
            await asyncio.sleep(_retry_delay(resp, attempt))
            continue
        return resp

    # Unreachable in practice (loop always returns or raises above), but
    # keeps type checkers happy and guards against future edits.
    if last_exc:
        raise _RequestFailed(f"{last_exc}") from last_exc
    raise _RequestFailed("request failed with no response")
