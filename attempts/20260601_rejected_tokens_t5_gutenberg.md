# tokens_t5_gutenberg

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: T5 token IDs for Gutenberg
- Source: https://www.gutenberg.org/
- Why it looked promising: The output is numeric, but only after tokenization.
- Failure class: policy_mismatch
- What happened: Token IDs are symbolic remappings produced by a tokenizer, not native numeric content.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Do not retry unless symbolic token corpora become in-scope.
