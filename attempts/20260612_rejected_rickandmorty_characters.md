# rickandmorty_characters

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: Rick and Morty character catalog
- Source: https://rickandmortyapi.com/
- Why it looked promising: Public structured API with numeric identifiers and measurements from a source family not otherwise represented in the collection.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be too small and too low-density as a standalone dataset, with only `100` total values and `240` sample bytes.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `rickandmorty_characters` at `100` total values, `240` total sample bytes, and `5` sample rows before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `rickandmorty_characters` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only if re-scoped into a materially larger media or fictional-knowledge family with enough numeric content to clear the floor.
