# eeg_physionet

- Date: 2026-06-01
- Status: needs_tooling
- Candidate dataset: PhysioNet EEG Motor Movement/Imagery
- Source: https://physionet.org/content/eegmmidb/1.0.0/
- Why it looked promising: EEG waveform channels would add useful biomedical numeric structure.
- Failure class: missing_decoder_tooling
- What happened: The external ingestion depends on EDF parsing, which is not yet present in this repo's recipe toolkit.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Record as tooling-limited instead of shipping a brittle parser under time pressure.
- Retry conditions: Retry after adding a reusable EDF parser workflow to this repo.
