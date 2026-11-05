# PRD-21598 · Code review

Status: frozen @ 62623bd9b7f6f17582b206f2d7b73c0242908041

## Round 1 · 2026-11-05 · reviewed dev/PRD-21598 @ 62623bd (base fda1c34)

Verdict: approved

### Scope

Diff `fda1c34..62623bd` on `MSPbotsAIFramework/ingrammicro-mcp`: adds `ingrammicro_cloud_create_change_order` as a second method/tool on the already-merged `CloudMarketplaceClient` / `tools/cloud.py` (PRD-21595), per the design's own merge-order note. Touches `cloud_api_client.py`, `tools/cloud.py`, `server.py` (instructions string only), `README.md` (Tool List / Known Gaps), tests, and the ticket's own `docs/tickets/PRD-21598.{md,ac.json}`. No changes to the 24 existing Resellers tools, no new credential headers (reuses PRD-21595's `X-IngramMicroCloud-Api-Key` / `X-IngramMicroCloud-Customer-Id`), no new dependency.

### Findings

1. [suggestion] src/ingrammicro_mcp/tools/cloud.py:672-675 — when a `products` item is not a dict, the returned `invalid_argument` message says "each products item requires mpn." even though the actual problem is the item's type, not a missing field. Cosmetic only — still correctly returns `invalid_argument` with no HTTP call (AC3 holds); not a correctness or security issue.

### Checks performed

- Diff read in full (`mbp.py diff --code`); matches the tech design's Change list and Data & API contract (Decision 1/2/3/4) verbatim — `subscriptionId` placed per-product-item, `customerId` sourced from the credential-bound client (not a tool/body argument supplied by the caller), `type="change"` unconditionally (AC1/AC2 share one code path, no purchase/remove branch), optional `po_number`/`billing_period`/`subscription_period`/`total` only added to the body when given (Q1 kept open, non-blocking).
- AC1–AC8 each map 1:1 to a test in `tests/test_cloud_tools.py` (ids in file header match `docs/tickets/PRD-21598.ac.json` TC1–TC8); TC9 is `manual`/`blocked` on a real vendor account, which is non-blocking per `mcp-track.md` §3's "no test account is not a blocker" rule.
- MCP checklist (`mcp-track.md` 4.3 / SOP §14): credentials only read from the two Cloud headers via the existing `GatewayTokenMiddleware`/contextvar wiring, never a tool/body argument, never logged or cached (AC5/AC7); `CloudMarketplaceClient` built fresh per request via `cloud_client_factory`, no shared mutable state added; errors are the existing structured `error_envelope`/`IngramMicroError.to_envelope()` shape, `retryable` reused from the existing `_classify`/`_STATUS_TO_CODE` plumbing in `_http.py` (unchanged by this diff); retry/backoff reused from `_request_with_retry` (unchanged); tool/parameter/return/error shapes match the tech design; `ToolAnnotations(destructiveHint=True, idempotentHint=False)` matches the order-submitting nature of the tool, same as the existing `ingrammicro_create_cloud_order`.
- No Chinese characters in any file this ticket touches (`grep -rnP '[\x{4e00}-\x{9fff}]'` across the worktree: only pre-existing hits in `docs/tickets/PRD-21595.md`/`PRD-21597.md`, verbatim-quoted ticket text from those earlier tickets, none in this ticket's own files).
- README `## MSPbots Connector` section untouched by this diff (pre-existing, from an earlier ticket) — only the `## Tool List` tool count/table and `Known Gaps` bullet were edited, consistent with the self-test's own claim.
- Scope check: no changes to any of the 24 existing Resellers-API tools, `IngramMicroClient`, or `config.py`/`server.py` credential wiring — purely additive, matches Non-goals.
- Self-test section in `docs/tickets/PRD-21598.md` reports gates run on code synced with `origin/main` (`uv run pytest`: 66 passed; `uv run ruff check .`: clean; `tools/list`: 27 tools) — not re-run in this review per `legs/review.md` R3 ("不重跑用例"); no finding here required a confirmation command.

No must-fix. Proceeding to merge into `main`, INT publish, and connector wiki per `mcp-track.md` §4.4/4.5.
