# PRD-21595 · Code review

## Round 1 · 2026-10-31 · reviewed dev/PRD-21595 @ 7801885 (base main @ 4171891)

Status: frozen @ 7801885

Verdict: approved

### Scope checked

`git diff origin/main...HEAD` (4171891..7801885): `.env.example`, `README.md`, `src/ingrammicro_mcp/_http.py` (new), `src/ingrammicro_mcp/api_client.py`, `src/ingrammicro_mcp/cloud_api_client.py` (new), `src/ingrammicro_mcp/config.py`, `src/ingrammicro_mcp/server.py`, `src/ingrammicro_mcp/tools/cloud.py` (new), `tests/test_cloud_tools.py` (new), `tests/test_middleware.py`, `tests/test_tools.py`, `docs/tickets/PRD-21595.md`, `docs/tickets/PRD-21595.ac.json`. Matches the tech design's Change list exactly — no out-of-scope files touched.

### Gates re-run independently (not just trusting the Self-test section)

- `uv sync` — ok on Python 3.12.
- `uv run ruff check .` — `All checks passed!`
- `uv run pytest -q` — `30 passed, 1 warning` (warning is the pre-existing starlette/httpx deprecation notice, unrelated).
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .` — 2 hits, both in `docs/tickets/PRD-21595.md` (a verbatim quote of the original ClickUp ticket text, and a quoted Chinese phrase inside a design rationale sentence) — none in `src/`, `tests/`, `README.md`, `.env.example`. Matches the Self-test claim (doc counted 1 hit; second hit is the `"有就跑"` quoted phrase on the gitleaks row, also inside the doc, same category).
- `README.md:11-81` vs `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md` — `diff` identical, confirmed byte-for-byte.
- No mypy/type-check gate declared for this repo (`pyproject.toml` has no `[tool.mypy]`) — `ruff` + `pytest` are the full gate set, consistent with `gates.md`.

### Findings

1. [suggestion] `src/ingrammicro_mcp/server.py:103-124` — `GatewayTokenMiddleware` returns a blanket 401 for the whole `/mcp` endpoint when any of the four Resellers headers (`X-IngramMicro-Client-Id` etc.) is missing, *before* the request ever reaches tool dispatch. The new Cloud headers are correctly treated as independent of that gate (confirmed by `test_missing_cloud_headers_does_not_401_request_with_valid_resellers_headers`), but the reverse case isn't: a tenant who only has IM Cloud Marketplace credentials and no Ingram Micro Resellers account can never reach `ingrammicro_cloud_list_subscriptions` at all — the whole connection is rejected before `tools/cloud.py` runs. This doesn't violate any AC (AC5 only specifies the missing-Cloud-headers case) and the ticket's actual tenant (Ginko IT) already uses this connector's Resellers tools, so this doesn't block shipping the change as scoped. Flagging for a future ticket: if a Cloud-only tenant onboarding scenario becomes real, the 401 gate needs to become per-tool-family rather than whole-connector.

No must-fix found. Credential handling (Header-only, no env fallback in gateway mode, per-request contextvar with `finally`-reset), multi-tenant isolation (AC7 — `customerId` sourced only from the constructor, never a call argument, verified by `test_client_always_sources_customer_id_from_constructor_not_call_args` and the `tools/list` inputSchema check), error envelope shape, and the `_http.py` extraction (refactor-only, no behavior change — verified: all pre-existing `api_client.py` tests still pass unmodified, and `IngramMicroError(0, ...)` is still raised the same way on network failure) all check out.

### Verdict rationale

- Design ↔ implementation: every AC (AC1-AC7) maps to a passing automated test; TC8 is the one case this repo's "no vendor account is not a blocker" rule exists for, correctly recorded as `blocked`/non-blocking rather than a false `pass`.
- Reuse: `_http.py` extraction removes the only duplication this change would have introduced; `IngramMicroError` reused instead of a second exception type; no new dependency.
- Backward compatibility: fully additive, confirmed by the full existing test suite passing unmodified.
- The one suggestion above doesn't rise to must-fix under `REVIEW.md`'s bar (would it fail BA's INT acceptance or break something live) — the actual ticket scenario is unaffected by it.
