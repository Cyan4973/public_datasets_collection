# open_notify_iss

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Open Notify ISS position snapshot
- Source: http://api.open-notify.org/iss-now.json
- Why it looked promising: Public operational telemetry endpoint with native numeric latitude, longitude, and timestamp fields.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single live snapshot with only `3` total values and `12` sample bytes. That is not meaningful training material under this repository's floor.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `open_notify_iss` at `3` total values, `12` total sample bytes, and `3` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `open_notify_iss` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only if re-scoped into a materially larger orbital/space telemetry family with time windows or entity coverage large enough to clear the floor.
