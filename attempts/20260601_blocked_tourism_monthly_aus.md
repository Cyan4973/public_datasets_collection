# tourism_monthly_aus

- Date: 2026-06-01
- Status: blocked
- Candidate dataset: Tourism Monthly AUS
- Source: https://huggingface.co/datasets/zaai-ai/time_series_datasets
- Why it looked promising: Pinned monthly macro covariates add a useful public numeric shape.
- Failure class: operational_scope
- What happened: The external reference is valid and on-scope, but the first exact-ID batch was narrowed to keep this sync pass operationally smaller.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Keep as an explicit deferred backfill target.
- Retry conditions: Retry after the first exact-ID batch is accepted.
