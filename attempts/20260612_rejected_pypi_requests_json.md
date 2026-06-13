# pypi_requests_json

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: PyPI `requests` package JSON metadata
- Source: `https://pypi.org/pypi/requests/json`
- Why it looked promising: Public package metadata with native file sizes, timestamps, and yanked flags.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single-package metadata slice with only `6` total values and `26` total sample bytes.
- Why more download does not save this recipe: The current recipe identity is one package (`requests`) and its finite release-file inventory. Even exhausting one package's file rows remains a tiny single-package artifact and does not approach the repository floor. Clearing the floor requires a multi-package recipe, not more download of this exact one-package endpoint.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `pypi_requests_json` at `6` total values, `26` total sample bytes, and `3` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `pypi_requests_json` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a broader homogeneous PyPI package-metadata recipe spanning many packages.
