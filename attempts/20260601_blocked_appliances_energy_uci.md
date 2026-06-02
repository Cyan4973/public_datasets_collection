# appliances_energy_uci

- Date: 2026-06-01
- Status: blocked
- Candidate dataset: UCI Appliances Energy Prediction
- Source: https://archive.ics.uci.edu/dataset/374/appliances+energy+prediction
- Why it looked promising: Residential energy and sensor time-series are useful numeric content.
- Failure class: operational_scope
- What happened: The external reference is valid and on-scope, but the first exact-ID batch was narrowed to keep this sync pass operationally smaller.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Keep as an explicit deferred backfill target.
- Retry conditions: Retry after the first exact-ID batch is accepted.
