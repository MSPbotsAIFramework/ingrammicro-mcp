"""Clients for Ingram Micro's IM Cloud / CloudBlue Marketplace product
line — separate from the Ingram Micro Resellers API that api_client.py
wraps, and (see below) internally split into two further sub-APIs with
two different, verified-separately auth schemes.

CloudMarketplaceClient.create_change_order (PRD-21598): added on top of
the already-merged list_subscriptions (PRD-21595) client below, per that
ticket's own design note that whichever of the two tickets lands second
should add its method to the already-merged client rather than
re-creating the file (docs/tickets/PRD-21595.md and PRD-21598.md, Tech
design -> Risks, Decision 4). Same api_key/customer_id/base_url, same
`Authorization: Bearer {api_key}` auth, same `_handle`/error shape —
built against the same verified CloudBlue Simple API "Change Order"
contract (docs.cloudblue.com/cbc/21.0/Simple-API/how-to-use/howto/orders/).

CloudMarketplaceClient (PRD-21595, subscriptions): built against the
independently-verified CloudBlue "Simple API" contract
(docs.cloudblue.com/cbc/21.0/Simple-API/how-to-use/howto/subscriptions/),
since Ingram's own two hosted copies of this spec
(developer.ingrammicro.com's Cloud Marketplace API PDF and
apidocs.cloud.im) could not be reached from that session's environment at
design time (see docs/tickets/PRD-21595.md, Risks: ECONNRESET/timeout on
both hosts). Direct `Authorization: Bearer {api_key}`, no token-exchange
step, re-verify against a real account or the PDF below before relying on
this for a new capability — see CloudMarketplaceProductsClient's docstring
for what that PDF actually says once it *is* reachable.

get_subscription (PRD-21596, get-by-id): added to this same class rather
than a new client/credential bundle -- it is the same Subscriptions object
and the same account as list_subscriptions above, just fetched by id. This
means it inherits list_subscriptions' open question (the PDF found for
CloudMarketplaceProductsClient suggests this class's auth exchange may be
wrong -- see README Known Gaps and this ticket's docs/tickets/PRD-21596.md
Decisions). Not fixed here: changing a credential/auth contract that
PRD-21595 already shipped and that was already reviewed and merged is a
separate, larger change than "add one more read method", and is flagged as
a suggested follow-up rather than done as a drive-by fix.

CloudMarketplaceProductsClient (PRD-21597, products): built against
Ingram Micro's own "Cloud Marketplace API.pdf"
(developer.ingrammicro.com/sites/default/files/2025-11/Cloud%20Marketplace%20API.pdf),
which this session fetched directly (HTTP 200, 103 pages) on 2026-10-31 —
apidocs.cloud.im itself still ECONNRESETs from this environment, same as
it did for PRD-21595, but Ingram's own PDF mirror of the same spec does
not. That PDF's own "Token Generation" / "Testing the Bearer Token"
sections (pp. 5-7) show Basic-auth `POST {base}/token` with a JSON body,
an `X-Subscription-Key` header sent on *every* call (including `/token`
itself), and a short-lived Bearer token returned from `/token` — not the
direct-API-key-as-Bearer-token shape CloudMarketplaceClient assumes above.
Kept as a second class rather than folded into CloudMarketplaceClient:
the two have entirely different credential material (client id/secret/
subscription key vs. a single api key) and now-confirmed-different auth
flows, the same "one client class per distinct auth scheme" split this
repo already uses between IngramMicroClient (Resellers) and
CloudMarketplaceClient (Cloud). See docs/tickets/PRD-21597.md, Tech
design, for the full rationale and the flagged follow-up (CloudMarketplace-
Client's own auth assumption is now suspect given this PDF — not fixed
here, out of this ticket's scope; see that doc's Reuse & cleanup section).
"""

import base64
from typing import Any

from ._http import _request_with_retry, _RequestFailed
from .api_client import IngramMicroError


def _error_message(resp: Any) -> str:
    """Shared error-detail extraction for both Cloud Marketplace clients
    below (identical response shape assumptions: a JSON body with a
    "message" or "error" key, or plain text). Extracted so
    CloudMarketplaceProductsClient does not duplicate
    CloudMarketplaceClient's inline version of this logic.
    """
    try:
        detail = resp.json()
        if isinstance(detail, dict):
            return detail.get("message") or detail.get("error") or str(detail)
        return str(detail)
    except ValueError:
        return resp.text


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

    async def get_subscription(self, subscription_id: str) -> Any:
        """GET {base_url}/subscriptions/{id} (PRD-21596). Same client, same
        auth header, same retry policy as list_subscriptions above -- this
        is the same Subscriptions object, just fetched by id instead of
        listed. No customer_id query param: per apidocs.cloud.im
        ("/1.9/howto/subscriptions/"), the by-id lookup is not filtered by
        customer, unlike the list endpoint -- this call relies on the
        upstream API itself scoping the id to what this client's api_key
        can see, same trust boundary as every other call this client makes.
        """
        try:
            resp = await _request_with_retry(
                "GET",
                f"{self._base_url}/subscriptions/{subscription_id}",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
            )
        except _RequestFailed as e:
            raise IngramMicroError(0, e.message) from e
        return self._handle(resp)

    async def create_change_order(
        self,
        subscription_id: str,
        products: list[dict],
        po_number: str | None = None,
        billing_period: dict | None = None,
        subscription_period: dict | None = None,
        total: dict | None = None,
    ) -> Any:
        """POST {base_url}/orders with type="change" to add or remove
        license seats on an existing subscription. `subscription_id` is a
        tool-level parameter (one subscription per call) but is placed
        inside each `products[]` item in the request body as
        `subscriptionId`, matching the one verified CloudBlue example
        (docs/tickets/PRD-21598.md, Tech design Decision 1) — not a
        top-level request field.

        `products[]` items carry the caller-supplied fields as-is
        (`mpn`, `quantity` as the new TOTAL count, optional `name`,
        `parameters`, `deals`) with `subscriptionId` merged in; nothing
        here renames, drops, or defaults any of those fields.
        """
        body: dict[str, Any] = {
            "customerId": self._customer_id,
            "type": "change",
            "products": [{**item, "subscriptionId": subscription_id} for item in products],
        }
        if po_number is not None:
            body["poNumber"] = po_number
        if billing_period is not None:
            body["billingPeriod"] = billing_period
        if subscription_period is not None:
            body["subscriptionPeriod"] = subscription_period
        if total is not None:
            body["total"] = total
        try:
            resp = await _request_with_retry(
                "POST",
                f"{self._base_url}/orders",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json_body=body,
            )
        except _RequestFailed as e:
            raise IngramMicroError(0, e.message) from e
        return self._handle(resp)

    def _handle(self, resp: Any) -> Any:
        if resp.status_code >= 400:
            raise IngramMicroError(resp.status_code, _error_message(resp))
        if resp.status_code == 204 or not resp.content:
            return []
        try:
            return resp.json()
        except ValueError:
            return {"raw_response": resp.text}


class CloudMarketplaceProductsClient:
    """Async httpx client for the IM Cloud Marketplace "Products" object
    (PRD-21597), verified against Ingram Micro's own "Cloud Marketplace
    API.pdf" (see module docstring for how/when this was fetched and what
    it says). Unlike CloudMarketplaceClient, this auth flow re-authenticates
    on every call via an explicit Basic -> Bearer token exchange (the PDF
    states the token is short-lived, ~1500s, and this repo's existing
    clients already follow a no-caching, re-auth-per-call pattern for the
    same multi-tenant-correctness reason — see IngramMicroClient._login).

    No customer/tenant id is part of this API's contract at all (the
    `/products` endpoint is a vendor-scoped catalog lookup, not scoped to a
    reseller's own customer) — so, unlike CloudMarketplaceClient, there is
    no fixed-at-construction tenant identifier to guard; the per-tenant
    isolation boundary here is simply that the five credential values
    (client id/secret/marketplace/subscription key/base url) are never
    read from anywhere but this instance's own constructor arguments,
    which the gateway middleware populates fresh from that one request's
    headers (see server.py's _gateway_cloud_products_creds_var).
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        marketplace: str,
        subscription_key: str,
        base_url: str,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._marketplace = marketplace
        self._subscription_key = subscription_key
        self._base_url = base_url.rstrip("/")

    async def _login(self) -> str:
        """POST {base}/token -> short-lived Bearer access token. Per the
        PDF (pp. 5-7): Basic-auth header (base64 client_id:client_secret),
        X-Subscription-Key on the token call itself (not just later
        calls), JSON body {"marketplace": "<code>"}.
        """
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        try:
            resp = await _request_with_retry(
                "POST",
                f"{self._base_url}/token",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "X-Subscription-Key": self._subscription_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json_body={"marketplace": self._marketplace},
            )
        except _RequestFailed as e:
            raise IngramMicroError(0, e.message) from e
        if resp.status_code >= 400:
            raise IngramMicroError(resp.status_code, _error_message(resp))
        try:
            body = resp.json()
        except ValueError:
            raise IngramMicroError(0, "Cloud Marketplace /token response was not JSON") from None
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            raise IngramMicroError(
                0, "Cloud Marketplace /token response did not include access_token"
            )
        return token

    async def list_products(
        self,
        vendor: str,
        mpn: str | None = None,
        name: str | None = None,
        service_name: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Any:
        token = await self._login()
        params = {
            "vendor": vendor,
            "mpn": mpn,
            "name": name,
            "serviceName": service_name,
            "limit": limit,
            "offset": offset,
        }
        clean_params = {k: v for k, v in params.items() if v is not None}
        try:
            resp = await _request_with_retry(
                "GET",
                f"{self._base_url}/products",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Subscription-Key": self._subscription_key,
                    "Accept": "application/json",
                },
                params=clean_params,
            )
        except _RequestFailed as e:
            raise IngramMicroError(0, e.message) from e
        if resp.status_code >= 400:
            raise IngramMicroError(resp.status_code, _error_message(resp))
        if resp.status_code == 204 or not resp.content:
            return {"products": []}
        try:
            return resp.json()
        except ValueError:
            return {"raw_response": resp.text}
