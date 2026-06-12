# frankfurter_usd_rates

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Frankfurter one-day USD FX rates snapshot
- Source: https://api.frankfurter.app/
- Why it looked promising: Public foreign-exchange source with real operational numeric rates from a distinct source family.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a one-day snapshot with only `30` total values and `240` sample bytes. That is too thin as a standalone dataset and should be replaced by a real multi-date FX recipe if the family is kept.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `frankfurter_usd_rates` at `30` total values, `240` total sample bytes, and `1` sample row before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `frankfurter_usd_rates` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a materially larger multi-date FX recipe with enough temporal depth to clear the floor.
