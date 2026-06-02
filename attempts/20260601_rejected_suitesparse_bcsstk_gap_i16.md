# suitesparse_bcsstk_gap_i16

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: SuiteSparse selector-gap streams
- Source: https://sparse.tamu.edu/
- Why it looked promising: The upstream sparse matrices are public, but the exported values are a derived selector-gap transform.
- Failure class: policy_mismatch
- What happened: The external recipe emits derived delta/gap streams rather than the native numeric matrix values.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Retry only if derived transforms become in-scope.
