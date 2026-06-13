# nagerdate_holidays

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Nager.Date US holidays for 2024
- Source: `https://date.nager.at/api/v3/PublicHolidays/2024/US`
- Why it looked promising: Public civic calendar data with native date and flag fields.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a single country-year holiday table with only `85` total values and `102` total sample bytes.
- Why more download does not save this recipe: The current recipe identity is one country (`US`) in one year (`2024`). That bounded table is already essentially complete for the chosen scope. Clearing the floor would require aggregating many country-years or redefining the recipe as a broader holiday corpus, which is materially different from this exact recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `nagerdate_holidays` at `85` total values, `102` total sample bytes, and `5` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `nagerdate_holidays` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a materially broader holiday-family recipe with explicit country and year coverage.
