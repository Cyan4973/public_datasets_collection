# usaspending_agencies

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: USAspending agencies catalog
- Source: https://api.usaspending.gov/
- Why it looked promising: Public government finance source with operational identifiers and agency metadata from an otherwise useful source family.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be intrinsically too small for this collection as a standalone dataset. The agency list is finite and too low-density to justify its own recipe compared with richer USAspending entities such as awards, obligations, or transactions.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `usaspending_agencies` at `888` total values and `5217` total sample bytes before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `usaspending_agencies` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only through a larger USAspending family recipe built from substantially richer entities.
