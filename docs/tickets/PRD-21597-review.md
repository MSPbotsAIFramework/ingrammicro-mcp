# PRD-21597 · Code review

## Round 1 · 2026-10-31 · reviewed dev/PRD-21597 @ a3127fa (base cb8d4e2)

Verdict: approved

### Findings

No must-fix findings.

1. [suggestion] `src/ingrammicro_mcp/server.py:176-224`, `docs/tickets/PRD-21597.ac.json` (TC-CLOUD-006) — the gateway's blanket 401 for the 4 Resellers headers was deliberately left unchanged, so a Cloud-Products-only caller (no Resellers headers at all) still gets a 401 at the gateway layer before reaching the tool. This is a scope-narrowing from the tech design's original Conclusion (which proposed loosening the gate), but no AC in this ticket's AC1-AC7 actually requires the narrower behavior (AC4/AC5 only test the inverse: Cloud headers absent, with/without Resellers present), and the identical gap was already raised and explicitly accepted as a non-blocking suggestion in sibling ticket PRD-21595's own round-1 review (approved) for the Cloud Subscriptions bundle — same tenant (Ginko IT), same reasoning applies. `ac.json`'s TC-CLOUD-006 entry is left `"result": "fail"` with a full explanation in `"evidence"` rather than silently edited or dropped, which is the correct handling per this pipeline's rule that only the design leg may change what a test case asserts. Not blocking; flagged here in case design ever revisits per-tool-family gating (tracked in the doc's Reuse & cleanup → Follow-ups #2).
2. [suggestion] `src/ingrammicro_mcp/cloud_api_client.py` module docstring — the dev leg independently re-verified the Cloud Marketplace auth shape against Ingram Micro's own published PDF and flagged that the sibling `CloudMarketplaceClient` (PRD-21595, already shipped) now looks auth-incorrect against that same PDF. Correctly left unfixed here (out of this ticket's scope, that code already reviewed and shipped) and filed as a named follow-up in both the doc and README Known Gaps. No action needed from this review; noting it here so it isn't lost if this ticket is referenced later.

### Verification performed

- `uv sync && uv run ruff check . && uv run pytest -q` on `dev/PRD-21597 @ a3127fa` (already synced with `main @ cb8d4e2`, confirmed via `git merge-base origin/main HEAD` == `cb8d4e2`): ruff clean, `51 passed, 1 warning` (warning is the pre-existing starlette/httpx `TestClient` deprecation notice, unrelated) — matches the `[DEV]` stub's claimed result exactly.
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv src tests README.md .env.example` — zero hits.
- `diff <(sed -n '11,81p' README.md) ~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md` — identical.
- Read full diff `cb8d4e2...a3127fa` (12 files, +1499/-46): `server.py`, `config.py`, `cloud_api_client.py`, `tools/cloud.py`, all three test files, `README.md`, `.env.example`, `docs/tickets/PRD-21597.{md,ac.json}`.
- Confirmed `_request_with_retry`/`IngramMicroError`/`_classify` signatures in `_http.py`/`api_client.py` match how `CloudMarketplaceProductsClient` calls them (AC6 error-envelope path) — no hallucinated API usage.
- Confirmed AC1-AC8 (AC1-AC7 from the doc, TC-CLOUD-001..009 from `ac.json`) each map to a passing test, except TC-CLOUD-006 (see Findings #1, suggestion only) and TC-CLOUD-009 (manual, blocked on a real vendor account — acceptable per `mcp-track.md`'s completion criteria).
- Confirmed the new third credential bundle (`_gateway_cloud_products_creds_var`) is isolated from the existing two (Resellers, Cloud Subscriptions) via `test_two_cloud_bundles_isolated_in_the_same_request`, and that a Resellers-only request is unaffected (`test_missing_cloud_products_headers_does_not_401_request_with_valid_resellers_headers` — AC5 regression guard).
- No credentials hardcoded, logged, or persisted; no new third-party dependency added (`respx` was already a declared, unused dev dependency).

### Scope

Single repo (`MSPbotsAIFramework/ingrammicro-mcp`), `vendor-mcp` track, no platform half. Release order: `any` (per `[DEV]` stub and doc Handoff).

---

Status: frozen @ a3127fa
