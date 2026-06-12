# pypistats_recent

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: PyPIStats recent package counters
- Source: https://pypistats.org/api/
- Why it looked promising: Public operational package ecosystem metrics from a relevant software-infrastructure source family.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single-package, recent-counter snapshot with only `3` total values and `24` sample bytes. The source family is real, but this exact recipe shape is too thin to justify a standalone dataset.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `pypistats_recent` at `3` total values, `24` total sample bytes, and `3` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `pypistats_recent` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a broader multi-package and/or longer-window PyPI statistics recipe with enough numeric content to clear the floor.
