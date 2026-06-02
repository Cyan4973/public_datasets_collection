# ud_deprel_u8

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: Universal Dependencies DEPREL IDs
- Source: https://universaldependencies.org/
- Why it looked promising: The source is public, but the output is a categorical label-ID stream.
- Failure class: policy_mismatch
- What happened: Dependency labels are mapped to integer IDs. That is symbolic remapping, not preservation of native numeric content.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Retry only if symbolic linguistic annotations become in-scope.
