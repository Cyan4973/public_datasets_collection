# mitbih_arrhythmia_physionet

- Date: 2026-06-01
- Status: needs_tooling
- Candidate dataset: PhysioNet MIT-BIH Arrhythmia
- Source: https://physionet.org/content/mitdb/1.0.0/
- Why it looked promising: Long ECG waveform records are clearly on-scope numeric content.
- Failure class: missing_decoder_tooling
- What happened: Porting the external recipe cleanly requires a reusable WFDB 212 decoder and a higher-confidence waveform validation path. That helper is not yet present in this repo.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Do not fake the import; record the tooling gap.
- Retry conditions: Retry after adding a reusable WFDB ingestion helper to this repo.
