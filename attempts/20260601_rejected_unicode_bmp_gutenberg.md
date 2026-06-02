# unicode_bmp_gutenberg

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: Unicode BMP Gutenberg codepoints
- Source: https://www.gutenberg.org/
- Why it looked promising: Public corpus, but the output is a character-code stream over text.
- Failure class: policy_mismatch
- What happened: Character codepoint sequences are symbolic text encodings, not numeric measurement data. The external repo already removed this entry on that basis.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Do not retry unless the repo scope changes materially.
