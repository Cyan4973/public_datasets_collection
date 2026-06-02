# omniglot_selector_gap_i16

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: Omniglot selector-gap streams
- Source: https://github.com/brendenlake/omniglot
- Why it looked promising: The upstream images are public, but the exported values are a derived selector-gap transform.
- Failure class: policy_mismatch
- What happened: The external recipe computes signed gap streams from image geometry, which is outside this repo's direct numeric acquisition scope.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Retry only if derived transforms become in-scope.
