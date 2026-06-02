# gas_sensor_array_drift_uci

- Date: 2026-06-01
- Status: blocked
- Candidate dataset: UCI Gas Sensor Array Drift Dataset
- Source: https://archive.ics.uci.edu/dataset/224/gas+sensor+array+drift+dataset
- Why it looked promising: Real dense sensor-array numeric data with cross-batch drift adds a useful industrial shape.
- Failure class: operational_scope
- What happened: The upstream dataset is valid and on-scope, but this sync pass kept the runnable exact-ID backfill batch smaller. The libsvm-like dense ingest remains a good next backfill after the first batch lands.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Keep as an explicit deferred backfill target rather than adding a partial recipe now.
- Retry conditions: Retry after the first exact-ID backfill batch is accepted.
