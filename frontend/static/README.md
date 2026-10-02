# Static reader assets

Vite copies this directory into the generated website. The generated `snapshot/` directory is ignored by Git; it is exported from the local database or checked out from the dedicated `site-data` branch during Pages builds. Legacy PDF viewer assets under `public/` are not included.

`deadlines.json` is an independent, public CCF A/B conference calendar derived from CCFDDL. Its upstream license is included in `data-sources/CCFDDL-LICENSE.txt`. It is loaded only on the calendar route and can be refreshed with `python backend/scripts/sync_deadlines.py` from the repository root. The generated timestamp is shown to readers; this is not a live CFP API.
