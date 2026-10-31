"""Client for Ingram Micro's IM Cloud / CloudBlue Marketplace API — a
separate product from the Ingram Micro Resellers API that api_client.py
wraps. Added for PRD-21595 (gap: list a customer's Cloud Marketplace
subscriptions, to find the M365-type subscription to add/remove seats on).

Built against the independently-verified CloudBlue "Simple API" contract
(docs.cloudblue.com/cbc/21.0/Simple-API/how-to-use/howto/subscriptions/),
since Ingram's own two hosted copies of this spec
(developer.ingrammicro.com's Cloud Marketplace API PDF and
apidocs.cloud.im) could not be reached from this environment at design
time (see docs/tickets/PRD-21595.md, Risks). The exact base URL and
whether Ingram's own deployment needs an OAuth2 exchange instead of a
direct API key (Q1/Q2 in that doc) are confirmed by whoever has network
access to those two hosts or a real account — only this file's internals
(_login/base URL/header names) would need to change, not the tool
signature in tools/cloud.py.
"""

from typing import Any

from ._http import _request_with_retry, _RequestFailed
from .api_client import IngramMicroError


class CloudMarketplaceClient:
    """Async httpx client for the IM Cloud / CloudBlue Marketplace
    "Subscriptions" object. Unlike IngramMicroClient (OAuth2
    client_credentials, re-logging in on every call), this API's generic
    CloudBlue documentation shows a direct `Authorization: Bearer
    {api_key}` header with no visible token-exchange step (Decision 2 in
    the tech design) — so there is no `_login()` here. If Ingram's own
    deployment turns out to need an exchange step, that goes here without
    touching the tool or the credential headers it reads.

    `customer_id` is fixed at construction time from the gateway
    credential header (X-IngramMicroCloud-Customer-Id) and is never
    accepted as a per-call argument — this is the multi-tenant isolation
    boundary for AC7: nothing in the tool layer can make this client ask
    for a different customer's subscriptions.
    """

    def __init__(self, api_key: str, customer_id: str, base_url: str):
        self._api_key = api_key
        self._customer_id = customer_id
        self._base_url = base_url.rstrip("/")

    async def list_subscriptions(
        self,
        status: str | None = None,
        creation_date_from: str | None = None,
        creation_date_to: str | None = None,
    ) -> Any:
        params = {
            "customerId": self._customer_id,
            "status": status,
            "creationDateFrom": creation_date_from,
            "creationDateTo": creation_date_to,
        }
        clean_params = {k: v for k, v in params.items() if v is not None}
        try:
            resp = await _request_with_retry(
                "GET",
                f"{self._base_url}/subscriptions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
                params=clean_params,
            )
        except _RequestFailed as e:
            raise IngramMicroError(0, e.message) from e
        return self._handle(resp)

    def _handle(self, resp: Any) -> Any:
        if resp.status_code >= 400:
            try:
                detail = resp.json()
                if isinstance(detail, dict):
                    msg = detail.get("message") or detail.get("error") or str(detail)
                else:
                    msg = str(detail)
            except ValueError:
                msg = resp.text
            raise IngramMicroError(resp.status_code, msg)
        if resp.status_code == 204 or not resp.content:
            return []
        try:
            return resp.json()
        except ValueError:
            return {"raw_response": resp.text}
