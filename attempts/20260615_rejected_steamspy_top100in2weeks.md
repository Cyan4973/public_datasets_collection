# steamspy_top100in2weeks

- Date: 2026-06-15
- Status: rejected
- Candidate dataset: SteamSpy top 100 in two weeks leaderboard
- Source: `https://steamspy.com/api.php?request=top100in2weeks`
- Why it looked promising: Public game usage and review counters from a distinct domain.
- Failure class: intrinsically_bounded_leaderboard
- What happened: The accepted recipe had only `400` total primary values, `1600` primary sample bytes, `4` sample rows, and median sample size `100` values.
- Why more download does not save this recipe: The endpoint is intrinsically a fixed top-100 leaderboard. Extending it would require changing to a different material, not downloading more of this dataset.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `steamspy_top100in2weeks` at `400` primary values with `aggregate_floor,median_sample_floor` before removal.
- Decision: Remove `steamspy_top100in2weeks` from `datasets/` and reject this bounded leaderboard recipe.
- Retry conditions: Retry only as a broader game catalog or time-series recipe with stable scope and enough natural sample size to clear the floor.
