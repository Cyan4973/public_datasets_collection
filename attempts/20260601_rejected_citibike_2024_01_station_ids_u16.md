# citibike_2024_01_station_ids_u16

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: Citi Bike station ID streams
- Source: https://citibikenyc.com/system-data
- Why it looked promising: Trip data is public, but station IDs are categorical identifiers.
- Failure class: policy_mismatch
- What happened: Station IDs are dictionary-coded categorical values, not native numeric measurements.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Retry only if identifier streams become in-scope.
