# ingrammicro-mcp

MCP server for the **entire Ingram Micro Reseller purchasing lifecycle** —
a stateless HTTP MCP service wrapping the full non-webhook surface of
Ingram Micro's Reseller REST API: product catalog/pricing, quotes, order
placement/change/cancel/lookup, invoices, renewals, special-pricing deals,
returns, and freight estimates.

**Tech stack:** Python 3.12 + uv + FastMCP (Starlette/Uvicorn)

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Why this exists instead of just using Ingram Micro's own MCP Server

Ingram Micro also publishes its own official, remote-hosted MCP Server
(`developer.ingrammicro.com/reseller/mcp-server`). Verified directly
against that page's own content (2026-09-01): it is **query-only** —
product/pricing search, quotes, invoices, returns, renewals, subscriptions,
and freight estimate. It never mentions "Create Order" or "Place Order"
anywhere, so it cannot place a purchase order.

Rather than deploying two separate Ingram Micro connectors (their query-
only MCP plus a second one just for ordering — which would mean
provisioning two separate sets of credentials for the same vendor, and
the agent having to pick between two connectors for overlapping
capability), this server reimplements the official MCP's query
capabilities itself, directly against the same underlying Reseller REST
API, and adds the order-placement/change/cancel capability the official
one lacks. **One connector, one set of credentials, full coverage** —
this server is meant to fully replace Ingram Micro's own MCP Server for
MSPbots' purposes, not run alongside it.

## Authentication

OAuth2 **client_credentials** grant — pure server-to-server, no browser
redirect — but via Ingram Micro's own documented shape: `GET
/oauth/oauth20/token` with `client_id`/`client_secret` as **query
parameters**, not the more common HTTP Basic Auth header. Verified against
Ingram Micro's own published OpenAPI spec
(`github.com/ingrammicro-xvantage/xi-sdk-openapispec`,
`openapispec/unified/XI-Resellers-API-Spec.json`, checked 2026-09-01), not
guessed.

Every real Orders/Quote-to-Order call additionally requires three
business-context headers Ingram Micro's own docs mark mandatory —
`IM-CustomerNumber`, `IM-CountryCode`, `IM-CorrelationID` — plus an
optional `IM-SenderID`. `IM-CorrelationID` must be unique per transaction,
so this server generates a fresh UUID for every call itself; it is not
something the caller supplies.

**Getting credentials is not self-serve.** Per Ingram Micro's own
onboarding docs, applying for API access requires:
- An **existing, active Ingram Micro reseller account** in good standing
- **Current sales history** with Ingram Micro
- Sandbox testing, then a formal app-approval submission (~2 business days)

This is a real prerequisite, not a formality — confirm the tenant already
has an active Ingram Micro reseller relationship before attempting to
provision credentials for this server.

Since this is a stateless multi-tenant service, the token is **not
cached** — every tool call re-authenticates from scratch (same pattern as
`cisco-umbrella-mcp`/`covedataprotection-mcp`/`webroot-mcp`).

### HEADER Authorization Parameters

| Header | Type | Required | Default | Allowed values | Description | Example |
|---|---|---|---|---|---|---|
| `X-IngramMicro-Client-Id` | string | Yes | None | None | Client ID for OAuth2 client_credentials | `abc123...` |
| `X-IngramMicro-Client-Secret` | string | Yes | None | None | Client Secret for OAuth2 client_credentials | `xyz789...` |
| `X-IngramMicro-Customer-Number` | string | Yes | None | None | Ingram Micro reseller account number (maps to upstream `IM-CustomerNumber`), e.g. `20-222222` | `20-222222` |
| `X-IngramMicro-Country-Code` | string | Yes | None | None | Two-letter ISO country code (maps to upstream `IM-CountryCode`) | `US` |
| `X-IngramMicroCloud-Api-Key` | string | No | None | None | API key for the separate IM Cloud / CloudBlue Marketplace API — only needed to call `ingrammicro_cloud_list_subscriptions` | `ck_abc123...` |
| `X-IngramMicroCloud-Customer-Id` | string | No | None | None | Customer id in the IM Cloud Marketplace (not the same id space as `X-IngramMicro-Customer-Number` above) | `cust-42` |
| `X-IngramMicroCloud-Products-Client-Id` | string | No | None | None | Basic-auth client id for the IM Cloud Marketplace **Products** API — a third, independent credential bundle, only needed to call `ingrammicro_cloud_list_products` | `pid-abc123...` |
| `X-IngramMicroCloud-Products-Client-Secret` | string | No | None | None | Basic-auth client secret for the same `/token` exchange | `psecret-xyz789...` |
| `X-IngramMicroCloud-Products-Marketplace` | string | No | None | None | Marketplace/region code sent in the `/token` request body | `us` |
| `X-IngramMicroCloud-Products-Subscription-Key` | string | No | None | None | `X-Subscription-Key` value issued at onboarding — sent on every call, including `/token` itself | `066a6b...` |
| `X-IngramMicroCloud-Products-Base-Url` | string | No | None | None | This reseller's IM Cloud Marketplace Products API host (not a public constant — see Known Gaps) | `https://api.cloud.im` |

Missing any of the four Resellers headers returns `401 Unauthorized`. The `X-IngramMicroCloud-*` and `X-IngramMicroCloud-Products-*` headers are independent of those four and of each other: a caller that never sends them still gets full access to every other tool in this server — only `ingrammicro_cloud_list_subscriptions` / `ingrammicro_cloud_list_products` themselves return a `not_configured` error envelope when their own bundle is absent or incomplete.

## Quick Start

### Docker (recommended)

```bash
docker compose up --build
```

The server starts on `http://localhost:8080`.

### Local (uv)

```bash
uv sync
python -m ingrammicro_mcp
```

## Health Check

```bash
curl http://localhost:8080/health
# {"status": "ok"}
```

No credentials are required for the health endpoint.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `http` (production) or `stdio` (local dev) |
| `MCP_HTTP_PORT` | `8080` | Listening port |
| `MCP_HTTP_HOST` | `0.0.0.0` | Listening host |
| `AUTH_MODE` | `gateway` | `gateway` (per-request headers, SOP-compliant) or `env` (shared credential, local dev only) |
| `INGRAMMICRO_CLIENT_ID` / `_CLIENT_SECRET` / `_CUSTOMER_NUMBER` / `_COUNTRY_CODE` | — | Only used in `env` mode |
| `INGRAMMICRO_SENDER_ID` | `MSPbots` | `IM-SenderID` value sent on every call |
| `INGRAMMICRO_BASE_URL` | `https://api.ingrammicro.com` | Override for sandbox testing (see Known Gaps — the exact sandbox URL is unverified) |
| `INGRAMMICRO_CLOUD_API_KEY` / `_CLOUD_CUSTOMER_ID` | — | Only used in `env` mode, for `ingrammicro_cloud_list_subscriptions` |
| `INGRAMMICRO_CLOUD_BASE_URL` | — (no default) | IM Cloud / CloudBlue Marketplace API host — no hardcoded default since the exact host is unverified (see Known Gaps); the tool returns `not_configured` until this is set |
| `INGRAMMICRO_CLOUD_PRODUCTS_CLIENT_ID` / `_CLIENT_SECRET` / `_MARKETPLACE` / `_SUBSCRIPTION_KEY` / `_BASE_URL` | — | Only used in `env` mode, for `ingrammicro_cloud_list_products` — a third, independent credential bundle (see Authentication above) |

## Tool List

26 tools: 24 covering every non-webhook endpoint in Ingram Micro's
Resellers API, plus 2 for the separate IM Cloud Marketplace product line
(see below — subscriptions and products are independent credential
bundles). Every order-placing/modifying tool spends real money against the
reseller's Ingram Micro net-terms account — **Ingram Micro does not
support credit-card API ordering**, only net-terms trade credit, so a
mistaken order is a real invoice, not a rejected charge.

### Catalog (corresponds to the official MCP: Product Info & Pricing)

| Tool | Description | Method + Path |
|---|---|---|
| `ingrammicro_search_products` | Search the product catalog by keyword/vendor/category | GET /resellers/v6/catalog |
| `ingrammicro_get_product_detail` | Get product details by Ingram Part Number | GET /resellers/v6/catalog/details/{ingramPartNumber} |
| `ingrammicro_get_product_detail_by_reference` | Get product details by vendor part number / subscription plan id or name | GET /resellers/v6/catalog/details |
| `ingrammicro_get_price_and_availability` | Get real-time price and stock | POST /resellers/v6/catalog/priceandavailability |

### Quotes (corresponds to the official MCP: Quotes)

| Tool | Description | Method + Path |
|---|---|---|
| `ingrammicro_search_quotes` | Search quotes | GET /resellers/v6/quotes/search |
| `ingrammicro_get_quote` | Get quote details | GET /resellers/v6/quotes/{quoteNumber} |
| `ingrammicro_create_quote` | Create a quote (reserves the price, does not place an order) | POST /resellers/v6/quotes/create |
| `ingrammicro_validate_quote_to_order` | Validate a quote before converting it to an order, returns required fields | GET /resellers/v6/q2o/validatequote |

### Orders (corresponds to the official MCP: Orders, but the official one is read-only; placing/modifying/cancelling orders are capabilities the official one does not have)

| Tool | Description | Method + Path | Main parameters |
|---|---|---|---|
| `ingrammicro_create_order` | Place an order: stock / direct-ship / licensing / warranty SKUs | POST /resellers/v6/orders | `customer_order_number` (required), `lines` (required), `ship_to_info`, `end_user_info`, `reseller_info`, `shipment_details`, `vendor_auth_number` (required for warranty orders) |
| `ingrammicro_create_cloud_order` | Place an order: cloud subscription / Quote-to-Order / Configure-to-Order (asynchronous, the result is pushed via webhook and is not in this response) | POST /resellers/v7/orders | exactly one of `quote_number` or `lines` (one must be given) |
| `ingrammicro_modify_order` | Modify an order: only orders with the customer-hold flag, within 24 hours after placing | PUT /resellers/v6/orders/{orderNumber} | `order_number` (required), `action_code` (e.g. "release"), `lines` (ADD/UPDATE/DELETE) |
| `ingrammicro_cancel_order` | Cancel an order: only before it has been released to the warehouse | DELETE /resellers/v6/orders/{OrderNumber} | `order_number` (required) |
| `ingrammicro_get_order` | Get details / shipping status of a single order | GET /resellers/v6.1/orders/{ordernumber} |
| `ingrammicro_search_orders` | Search orders by PO number / status / product | GET /resellers/v6/orders/search |

### Invoices (corresponds to the official MCP: Invoices)

| Tool | Description | Method + Path |
|---|---|---|
| `ingrammicro_search_invoices` | Search invoices | GET /resellers/v6/invoices |
| `ingrammicro_get_invoice` | Get invoice details | GET /resellers/v6.1/invoices/{invoiceNumber} |

### Renewals (corresponds to the official MCP: Subscriptions/Renewals)

| Tool | Description | Method + Path |
|---|---|---|
| `ingrammicro_search_renewals` | Search renewal opportunities | POST /resellers/v6/renewals/search |
| `ingrammicro_get_renewal` | Get renewal details | GET /resellers/v6/renewals/{renewalId} |

### Deals (special pricing / Special Bid; not listed separately in the official MCP, but also a query-type capability)

| Tool | Description | Method + Path |
|---|---|---|
| `ingrammicro_search_deals` | Search special pricing / Special Bid | GET /resellers/v6/deals/search |
| `ingrammicro_get_deal` | Get deal details | GET /resellers/v6/deals/{dealId} |

### Returns (corresponds to the official MCP: Returns)

| Tool | Description | Method + Path |
|---|---|---|
| `ingrammicro_search_returns` | Search return (RMA) requests | GET /resellers/v6/returns/search |
| `ingrammicro_get_return` | Get return details | GET /resellers/v6/returns/{caseRequestNumber} |
| `ingrammicro_create_return` | Submit a return request | POST /resellers/v6/returns/create |

### Freight (corresponds to the official MCP: Freight & Shipping)

| Tool | Description | Method + Path |
|---|---|---|
| `ingrammicro_get_freight_estimate` | Freight estimate | POST /resellers/v6/freightestimate |

### Cloud Marketplace (new — IM Cloud API, distinct from the Resellers API above)

A separate Ingram Micro product line (Cloud Marketplace subscriptions and
products, e.g. Microsoft 365 plans/SKUs), itself split into two
independent sub-APIs with two different auth schemes and credential
headers — see HEADER Authorization Parameters above. Neither requires the
four Resellers headers, and the two Cloud Marketplace tools below do not
require each other's headers.

| Tool | Description | Method + Path |
|---|---|---|
| `ingrammicro_cloud_list_subscriptions` | List this customer's Cloud Marketplace subscriptions (filterable by status, creation-date range) — use to find the subscription to add/remove seats on | GET /subscriptions |
| `ingrammicro_cloud_list_products` | Look up sellable Cloud Marketplace products by vendor code (filterable by mpn/name/serviceName, paginated) — use to find a Microsoft 365 (or other vendor) SKU mpn/name to quote | GET /products |

Complex nested parameters (`lines`/`ship_to_info`/`end_user_info`/`reseller_info`/`shipment_details`/`additional_attributes`/`products`/`returns`, etc.) are passed as `dict`/`list[dict]`; see each tool's own parameter description for the exact fields (field names have been verified against the official OpenAPI spec).

`ingrammicro_search_quotes`/`ingrammicro_create_quote`/`ingrammicro_get_freight_estimate` additionally require a `requester_email` parameter (maps to upstream `IM-CustomerContact`/`CustomerContact`: the email of the logged-in user making the request) - this is the caller's personal identity information, not a tenant-level credential, so it is a tool parameter rather than a gateway Header.

## Test Example

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-IngramMicro-Client-Id: <client_id>" \
  -H "X-IngramMicro-Client-Secret: <client_secret>" \
  -H "X-IngramMicro-Customer-Number: 20-222222" \
  -H "X-IngramMicro-Country-Code: US" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "ingrammicro_validate_quote_to_order",
      "arguments": { "quote_number": "QUO-14551943-D2Y9L9" }
    }
  }'
```

> ⚠️ This is a public repository; do not write sensitive information such as real client_id/client_secret/customer_number into any committed file.

## API Reference

- Official OpenAPI 3.0 spec (source of truth used for this build): https://github.com/ingrammicro-xvantage/xi-sdk-openapispec/blob/main/openapispec/unified/XI-Resellers-API-Spec.json
- Reseller API documentation portal: https://developer.ingrammicro.com/reseller/api-documentation/orders
- Getting started / account prerequisites: https://developer.ingrammicro.com/reseller/getting-started/api-overview
- Ingram Micro's own official MCP Server (query-only; this server supersedes it for MSPbots' purposes — see above): https://developer.ingrammicro.com/reseller/mcp-server

## Known Gaps

- **⚠️ Not yet verified against a real Ingram Micro account.** This build
  was written entirely from Ingram Micro's own published OpenAPI spec —
  schema/tool count confirmed via the real MCP protocol (`tools/list`, 24
  tools) and unit tests passing, but no call has been exercised against
  a real, credentialed Ingram Micro reseller account. Getting one requires
  an existing reseller relationship with sales history (see
  Authentication) — needs re-verification once real sandbox or production
  credentials are available.
- **Sandbox base URL is unconfirmed.** Ingram Micro's own sources
  disagree: the support/auth documentation references a
  `https://api.ingrammicro.com:443/sandbox` path, while the official
  OpenAPI spec's own `servers` block lists a single URL
  (`https://api.ingrammicro.com:443/`) labeled "Sandbox" with no `/sandbox`
  suffix. `INGRAMMICRO_BASE_URL` is fully overridable specifically so this
  can be corrected without a code change once confirmed.
- **`IM-ApplicationID` vs `IM-SenderID`**: Ingram's own spec documents
  Invoices/Deals-details as requiring `IM-ApplicationID` while every other
  endpoint documents the identical concept as `IM-SenderID`. Treated as a
  spec-naming inconsistency rather than two different things — this
  server sends both headers with the same configured sender id on every
  call rather than guessing which name a given endpoint actually
  validates.
- **Webhooks (`Order Status`, `Stock Update`) are out of scope.** These
  are inbound push notifications Ingram Micro sends *to* a callback URL a
  reseller registers — not something an MCP tool (which the agent *calls*)
  can meaningfully wrap. `ingrammicro_create_cloud_order` (v7) is
  documented as asynchronous specifically because its real result arrives
  via this webhook mechanism, not in the tool's own response — there is no
  tool here to receive or poll for that result; a separate webhook
  receiver component would be needed for that, out of scope for this
  build.
- **Complex nested body parameters (`lines`, `ship_to_info`,
  `end_user_info`, `reseller_info`, `shipment_details`,
  `additional_attributes`) are passed through as `dict`/`list[dict]`**
  rather than fully typed as individual Python parameters — the real
  request bodies have dozens of optional nested fields per object
  (verified against the spec, field names are accurate), but modeling
  every one as a typed parameter was out of scope. Field names/shapes are
  documented in each parameter's own description.
- **IM Cloud Marketplace API (`ingrammicro_cloud_list_subscriptions`) base
  URL and auth exchange are unverified against Ingram's own deployment —
  and now have a specific reason to suspect the auth exchange is wrong.**
  This tool was built against the independently-verified CloudBlue "Simple
  API" contract (Ingram's Xvantage Cloud Marketplace is built on CloudBlue
  Connect), since Ingram's own two hosted copies of this spec
  (`developer.ingrammicro.com`'s Cloud Marketplace API PDF and
  `apidocs.cloud.im`) could not be reached from the environment this tool
  was built in (PRD-21595). A later build (PRD-21597, below) *did* reach
  `developer.ingrammicro.com`'s PDF directly (`apidocs.cloud.im` still
  ECONNRESETs) — and that PDF documents a Basic-auth `POST /token` ->
  Bearer-token exchange with a static `X-Subscription-Key` header on every
  call, not this tool's assumed direct-API-key-as-Bearer-token shape. Not
  fixed here (out of scope for PRD-21597, which only adds
  `ingrammicro_cloud_list_products`) — whoever picks this gap up next
  should start from `developer.ingrammicro.com/sites/default/files/2025-11/Cloud%20Marketplace%20API.pdf`
  directly rather than re-attempting `apidocs.cloud.im`.
  `INGRAMMICRO_CLOUD_BASE_URL` has no hardcoded default specifically so
  the base URL can be set once confirmed, same pattern as the Resellers
  sandbox-URL gap above — only `cloud_api_client.py`'s internals would
  need to change, not the tool's parameters or any other file.
- **IM Cloud Marketplace Products API (`ingrammicro_cloud_list_products`)
  auth scheme is verified against Ingram's own PDF, but the real response
  shape and this reseller's actual base URL are not.** Unlike the
  subscriptions tool above, this tool's auth (Basic -> `POST /token` ->
  Bearer + `X-Subscription-Key`) comes directly from
  `developer.ingrammicro.com`'s own "Cloud Marketplace API.pdf" ("Token
  Generation" / "Testing the Bearer Token" sections), fetched successfully
  from this build's environment. What remains unverified: the exact
  `/products` response field names against a live account (the ticket's
  own field list — `mpn`/`name`/`vendor`/`serviceName`/`billingPeriods`/
  `prices` — is passed through unmodified, not re-modeled, so if the real
  API differs the mismatch will be visible rather than silently
  reshaped), and — same as every other base URL in this file —
  `X-IngramMicroCloud-Products-Base-Url` has no public constant and is
  handed out at onboarding, hence the per-request header rather than a
  hardcoded default.
