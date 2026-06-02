# ptbxl_physionet

- Date: 2026-06-01
- Status: needs_tooling
- Candidate dataset: PhysioNet PTB-XL
- Source: https://physionet.org/content/ptb-xl/1.0.3/
- Why it looked promising: Fixed-shape multi-lead ECG records would add another biomedical shape.
- Failure class: missing_decoder_tooling
- What happened: The external recipe relies on WFDB multi-file parsing and curated subset logic that is not yet ported here.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Record as tooling-limited for now.
- Retry conditions: Retry after adding reusable WFDB record handling in this repo.
