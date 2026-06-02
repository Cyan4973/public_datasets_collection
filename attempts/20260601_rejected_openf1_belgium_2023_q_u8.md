# openf1_belgium_2023_q_u8

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: OpenF1 quantized telemetry states
- Source: https://api.openf1.org/
- Why it looked promising: The source is public, but the external exact ID encodes quantized/categorical telemetry states.
- Failure class: policy_mismatch
- What happened: Brake and gear streams in the external exact ID are quantized or categorical transforms rather than faithful preservation of continuous upstream numeric measurements.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject the external exact ID for this repository.
- Retry conditions: Retry only if the repository chooses to admit quantized/categorical telemetry derivatives.
