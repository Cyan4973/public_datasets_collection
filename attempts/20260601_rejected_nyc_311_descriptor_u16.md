# nyc_311_descriptor_u16

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: NYC 311 descriptor IDs
- Source: https://data.cityofnewyork.us/
- Why it looked promising: The source is public, but the numeric output is a dictionary-coded text field.
- Failure class: policy_mismatch
- What happened: Descriptor IDs are categorical remappings, not native numeric observations.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Retry only if categorical text-ID datasets become in-scope.
