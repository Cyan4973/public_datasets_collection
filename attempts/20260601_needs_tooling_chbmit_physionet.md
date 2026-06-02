# chbmit_physionet

- Date: 2026-06-01
- Status: needs_tooling
- Candidate dataset: PhysioNet CHB-MIT
- Source: https://physionet.org/content/chbmit/1.0.0/
- Why it looked promising: Long-form EEG waveforms are on-scope and interesting.
- Failure class: missing_decoder_tooling
- What happened: The external plan depends on EDF parsing and channel-selection logic that is not yet ported here.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Record as tooling-limited for now.
- Retry conditions: Retry after adding reusable EDF parsing and channel selection helpers.
