# bf_snips_slots_u8

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: SNIPS coarse slot-label IDs
- Source: https://github.com/BrownFortress/IntentSlotDatasets
- Why it looked promising: Public dataset, but the numeric output is slot-label IDs.
- Failure class: policy_mismatch
- What happened: Slot labels are mapped to u8 IDs. That is symbolic remapping, not native numeric content.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject for this repository.
- Retry conditions: Retry only if symbolic NLP label streams become in-scope.
