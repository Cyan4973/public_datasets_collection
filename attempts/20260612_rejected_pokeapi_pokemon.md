# pokeapi_pokemon

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: PokeAPI Pokemon list ids
- Source: `https://pokeapi.co/api/v2/pokemon?limit=100`
- Why it looked promising: Public catalog API with native numeric Pokemon identifiers.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be a thin list-endpoint artifact with only `100` total values and `400` total sample bytes.
- Why more download does not save this recipe: The current recipe identity is the Pokemon list endpoint and the build emits only extracted resource ids. Even widening to the full Pokemon list remains a small finite id catalog. A meaningful version would require per-entity detail acquisition or a broader franchise dataset, which is materially different from the current recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `pokeapi_pokemon` at `100` total values, `400` total sample bytes, and `1` sample row before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `pokeapi_pokemon` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only as a materially broader Pokemon detail corpus or a different homogeneous media-data recipe.
