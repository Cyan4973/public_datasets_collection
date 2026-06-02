# loghub_templates_public

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: LogHub template ID streams
- Source: https://zenodo.org/records/8196385
- Why it looked promising: System logs are public and sequence-like, but the numeric outputs are template IDs.
- Failure class: policy_mismatch
- What happened: The external recipe normalizes text logs into template strings and then maps them to signed IDs. That violates this repo's numeric-content rule.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Retry only if the repository policy expands to admit symbolic remappings.
