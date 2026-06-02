# sensorless_drive_diagnosis_uci

- Date: 2026-06-01
- Status: blocked
- Candidate dataset: UCI Sensorless Drive Diagnosis
- Source: https://archive.ics.uci.edu/dataset/325/dataset+for+sensorless+drive+diagnosis
- Why it looked promising: Industrial current-drive features and an 11-class label add a manufacturing/fault-detection shape.
- Failure class: operational_scope
- What happened: The dataset is public and feasible, but this sync pass kept the runnable exact-ID backfill batch smaller. This recipe should come immediately after the first batch if the downloads land cleanly.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Keep as an explicit deferred backfill target.
- Retry conditions: Retry after the first exact-ID backfill batch is accepted.
