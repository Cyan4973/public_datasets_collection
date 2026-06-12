# freetogame_games

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: FreeToGame game catalog
- Source: https://www.freetogame.com/api/games
- Why it looked promising: Public gaming catalog with numeric identifiers and score-like metadata from a source family not otherwise represented in the collection.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe was audited and found to be intrinsically too small for this collection as a standalone dataset. The catalog is already near full coverage, but the numeric payload remains too sparse and too small to justify a dedicated recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `freetogame_games` at `1640` total values and `3280` total sample bytes before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `freetogame_games` from `datasets/` and reject it as a standalone accepted dataset.
- Retry conditions: Retry only if paired with a materially richer game-data source or expanded into a broader gaming-data family with enough numeric content to clear the floor.
