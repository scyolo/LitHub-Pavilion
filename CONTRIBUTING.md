# Contributor checks

Use Python 3.11/3.12 and Node 22. Install backend development requirements in a virtual environment and run `npm ci` in `frontend/`.

Before changing behavior:
1. Add a regression test in a temporary database or use `httpx.MockTransport`. Do not depend on a live upstream API in unit tests.
2. Preserve the user's data. New schema changes need a backup and explicit migration, never a delete/recreate shortcut.
3. Run `python -m ruff check app scripts tests --select F,E9` and `python -m pytest -o addopts= --disable-warnings` in `backend/`.
4. Run `npm test` and `npm run build` in `frontend/`.
5. When deployment changes, run the isolated Compose smoke test documented in README. Never use the real user's data volume for it.
6. Check the staged paths for databases, secrets, PDFs and generated vendor assets.

The UI must keep empty, loading, failed and unverified states distinct. A successful HTTP status or rising paper count is not proof of correct venue attribution or complete ingestion.
