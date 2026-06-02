# low_cardinality_u16_mirrors

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: Low-cardinality u16 mirrors
- Source: Derived from existing outputs
- Why it looked promising: It reuses public sources, but it is not an upstream dataset.
- Failure class: policy_mismatch
- What happened: The external entry is a derived widening of already-ingested public outputs, not a primary-source acquisition target.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Retry only if derived mirror datasets become in-scope.
