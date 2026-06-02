# ndbc_missingmask_u16

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: NDBC packed missingness masks
- Source: https://www.ndbc.noaa.gov/
- Why it looked promising: The underlying buoy data is public, but the external exact ID is a derived missingness encoding.
- Failure class: policy_mismatch
- What happened: Packed missingness bitmasks are derived annotations over other numeric measurements, not primary numeric content.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Retry only if derived mask datasets become in-scope.
