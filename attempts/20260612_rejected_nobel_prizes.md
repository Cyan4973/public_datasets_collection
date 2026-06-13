# nobel_prizes

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Nobel Prize award metrics for 2024
- Source: `https://api.nobelprize.org/2.1/nobelPrizes?nobelPrizeYear=2024`
- Why it looked promising: Public curated award data with native monetary and calendar fields.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be too small as a standalone dataset, with only `24` total values and `66` total sample bytes.
- Why more download does not save this recipe: The current recipe uses one year, but even widening it to the full Nobel prize history would still be a small finite award table. The Nobel prize corpus is on the order of hundreds of awards, not tens of thousands of observations, so the recipe family remains far below the repository floor.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `nobel_prizes` at `24` total values, `66` total sample bytes, and `4` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `nobel_prizes` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: None expected under the current repository floor unless small finite award tables become explicitly in-scope.
