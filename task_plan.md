# CCF coverage and reader performance — verified checkpoint (2026-10-02)

Scope: 338 configured CCF A/B sources, 16 directions, 2023–2026. Metadata and original publication links only; no PDF/full-text or database-wide archive downloads. Preserve manual edits and canonical identities.

## Completed verification

1. Added 285 verified papers: WWW2025 87, Middleware2023 24, SIGGRAPH2025 174. Restored 18 publisher-split subtitles only with exact same-DOI official-title agreement. Excluded 195 other-parent SIGGRAPH records.
2. Exported and database-checked 381,441 public records (381,433 in scope, 8 older preserved), revision 3d798240bffdabc2ac5bc4d601610a03568e1327b7879db36e5417c600d33938. Installed assets all verified (6,614); current association hashes all verified (12).
3. Direct sources 325; represented sources 336/338. Direct-or-associated zero-year units 117 → 114. This is NOT an official inventory completeness result.
4. New v6 paged reader: compact ranking rows, title positions, 3-digit term buckets, 256-card shards, rank before hydrate. Same-corpus old/new engine parity, complete title identity checks and bounded first-page transfer tests pass.
5. Backend 892 / frontend 177 tests, Ruff, production build, diff checks pass. Fresh browser fast/limited-mobile budgets pass. Hard 12-second Worker deadline tested under a blocked index; no automatic timeout retry; explicit reload recovers.
6. Homepage matrix previews 20 sources, with verified expand-all 338 access. Old snapshot preserved under release-artifacts/final-audit-20261002/previous-installed-snapshot. Local preview remains at 127.0.0.1:5181.

## Repository submission

User explicitly requested a repository commit. Target branch: codex/coverage-search-performance-20261002; origin: scyolo/LitHub-Pavilion. main automatically deploys Pages, so do not merge/main-push or publish site-data as an incidental source commit. Git log/status and the final chat are authoritative for actual commit/push status; this file is itself included in that change.

## Remaining limits / future work

- LISA/VEE 2023–2026 editions/successor status still unverified. No fabricated replacements.
- 114 zero-record year units include periodic, future/unpublished, and genuinely unresolved cases. Continue per-official-inventory reconciliation; source presence is not full coverage.
- WWW2025 OpenTOC recovered 87 verified research papers, not all 408 numbered research posters.
- Docker smoke unavailable locally because the daemon is not running. Do not describe it as passed.
- Online data publication and Pages deployment are separate from this source-only submission.

Evidence: docs/performance-coverage-20261002.md; seeds/remaining_proceedings_provenance.json; release-artifacts/final-audit-20261002/{coverage-final.json,remaining-source-years.json,performance-budgets.json,browser-fast-final.json,browser-limited-final.json,browser-functional-final.json,search-validation.json}.

## Resumption audit (2026-10-02)

The linked chat stopped at the final pre-commit step after an upstream API error. At recovery, the repository had no commit or remote branch for these changes. Preserve the existing 286-file staged change and the two final unstaged fixes.

1. [complete] Re-ran backend/frontend/build/static integrity checks and finished stable mobile/timeout browser checks; all passed.
2. [complete] Reviewed staged paths/content for accidental private data and documented verified coverage limits and fresh timings.
3. Source submission is limited to the dedicated branch. The commit containing this checkpoint, its upstream SHA, and release-artifacts/final-audit-20261002/submission-resumed.json record the actual commit/push/CI result; do not infer deployment or full inventory coverage from a source commit.

Recovery note: the CI workflow is .github/workflows/verify.yml, not ci.yml; enumerate existing workflow names rather than retrying the missing path.

Final recovery verification: backend 892 / frontend 177; full 381,441-title DB and snapshot identity checks; 6,614 + 12 asset hashes; all seven cold/warm browser cases; 12,277 ms bounded timeout, one request, 914 ms manual recovery. No new source imports. The DB checker must be invoked with python -m scripts.check_database_search from backend (direct file execution omits the app import root).
