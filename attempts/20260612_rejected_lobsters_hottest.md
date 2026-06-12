# lobsters_hottest

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Lobsters hottest page snapshot
- Source: https://lobste.rs/
- Why it looked promising: Public operational ranking data from a real community platform, with native scores and counts.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single ranked-page snapshot with only `100` total values and `350` sample bytes. That is too ephemeral and too thin to justify a standalone dataset.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `lobsters_hottest` at `100` total values, `350` total sample bytes, and `4` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `lobsters_hottest` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only through a materially larger Lobsters corpus or a broader ranked-content family with enough depth and duration to clear the floor.
