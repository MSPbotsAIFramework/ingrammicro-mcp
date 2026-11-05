# PRD-21596 · Code review

## Round 1 · 2026-11-05 · reviewed dev/PRD-21596 0918f69 (base fda1c34)

Verdict: approved

### Findings

No must-fix found.

Suggestions (not blocking):
1. [suggestion] src/ingrammicro_mcp/cloud_api_client.py:136 — `subscription_id` is interpolated into the URL path without encoding. Consistent with every other id-path tool in this repo (`tools/quotes.py:91` `f"/resellers/v6/quotes/{quote_number}"`, `tools/renewals.py:87` `f"/resellers/v6/renewals/{renewal_id}"`), so not unique to this ticket — a repo-wide cleanup, not a PRD-21596 fix.
2. [suggestion] src/ingrammicro_mcp/config.py:71, server.py:95 — the new `X-IngramMicroCloud-Base-Url` per-request override accepts any string with no scheme/host validation before being used as the client's base URL (credentialed requests follow it). Same pattern already shipped for the Cloud Products bundle's own `X-IngramMicroCloud-Products-Base-Url` (PRD-21597), so this ticket is consistent with existing precedent, not introducing a new gap.

### Verification performed

- `git diff fda1c34..0918f69 --stat` and per-file diffs for all 12 changed files.
- `uv sync && uv run pytest -q` re-run independently on the worktree: `65 passed, 1 warning` — matches the `[DEV]` stub's claim.
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .` re-run repo-wide (not just the dev-leg's narrower `src tests README.md .env.example` scope): hits are all pre-existing quoted Chinese ticket text / SOP phrases inside `docs/tickets/*.md` (same category already accepted in PRD-21595/PRD-21597 reviews), none in `src/`, `tests/`, `README.md`, `.env.example`, or the new `.ac.json`.
- `diff` of README.md lines 11-81 against `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md` — identical, confirms the Self-test claim.
- Checked AC1-AC9 mapping: every AC has a test, `.ac.json` evidence lines match actual test names/results.
- Checked the dev-leg's tech-design deviation (reusing PRD-21595's `CloudMarketplaceClient` instead of building a new client/credential bundle as originally designed): this is a tech-design choice, not a user-visible behavior change, and is explicitly within dev's freedom per the pipeline rules; it also avoids ~80 lines of duplicated client logic. Accepted.
- Checked AC5 (backward compatibility): `_gateway_cloud_creds_var` tuple grew from 2 to 3 elements; both call sites and both pre-existing tests (`test_cloud_header_present_reaches_request_context_and_resets`, `test_two_cloud_bundles_isolated_in_the_same_request`) were updated for the new shape and still pass — no silent break.
- Checked credential/security hygiene: new headers (`X-IngramMicroCloud-Api-Key`, `-Customer-Id`, reused; `-Base-Url`, new) are read from request headers only, no logging, no disk writes, no shared state across requests (contextvar reset after each request).

Conclusion: single-repo, additive change (27th tool), zero behavior change for existing tools (AC5 satisfied by construction, verified live and by test), gates pass on code already synced with `main`. No must-fix. Proceeding to merge.

### Scope

Single repo (`MSPbotsAIFramework/ingrammicro-mcp`), `vendor-mcp` track, no platform half. Release order: `any` (per `[DEV]` stub and doc Handoff).

---

Status: frozen @ 0918f69
