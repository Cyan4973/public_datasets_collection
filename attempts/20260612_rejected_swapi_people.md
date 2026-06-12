# swapi_people

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: SWAPI people catalog
- Source: https://swapi.py4e.com/api/people/
- Why it looked promising: Public structured API with numeric identifiers and measurements from a source family not otherwise represented in the collection.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be intrinsically too small for this collection as a standalone dataset. The people resource is tiny, finite, and not meaningful enough on its own to justify a recipe slot.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `swapi_people` at `60` total values and `110` total sample bytes before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `swapi_people` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only if re-scoped into a materially larger Star Wars data family with enough numeric content to clear the floor.
