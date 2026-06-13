# tourism_monthly_aus

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: Tourism Monthly AUS exact-id backfill from pinned tourism CSV
- Source: `https://huggingface.co/datasets/zaai-ai/time_series_datasets/resolve/1229de3483f31edf12057b7a0775902c1ef1fc3b/data.csv`
- Why it looked promising: Public monthly time-series data with large aggregate totals and many emitted samples from one pinned upstream file.
- Failure class: tiny_sample_geometry
- What happened: The accepted recipe was re-audited under the new sample-geometry rule and failed because its samples are uniformly too small. It emits `138228` total values and `1105824` total sample bytes, but the median sample has only `228` values (`1824` bytes).
- Why more download does not save this recipe: The current recipe identity is one pinned upstream CSV with per-`unique_id` sample boundaries. That file is already complete for the chosen scope, so there is no honest pagination or time-range widening inside this exact recipe. Making samples materially larger would require redefining the corpus or changing the sample boundary, which is a different recipe.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `tourism_monthly_aus` at `138228` total values, `1105824` total sample bytes, `608` sample rows, and median sample size `228` values before removal.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `tourism_monthly_aus` from `datasets/` and reject this exact pinned-file, per-`unique_id` recipe shape.
- Retry conditions: Retry only as a materially different tourism-family recipe with substantially larger per-sample histories.

