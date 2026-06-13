# jolpica_f1_results

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Jolpica F1 results for the 2024 Bahrain Grand Prix
- Source: `https://api.jolpi.ca/ergast/f1/2024/1/results.json`
- Why it looked promising: Public structured sports data with native race result and timing fields.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single-race slice with only `98` total values and `272` total sample bytes.
- Why more download does not save this recipe: The current recipe identity is one race. Even widening to a full season still yields only a few dozen race-result rows per season and remains far below the repository floor. A viable version would need a multi-season or broader motorsport corpus, which is a different recipe shape.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `jolpica_f1_results` at `98` total values, `272` total sample bytes, and `5` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `jolpica_f1_results` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a materially broader multi-season racing-results recipe.
