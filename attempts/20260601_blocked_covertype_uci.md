# covertype_uci

- Date: 2026-06-01
- Status: blocked
- Candidate dataset: UCI Covertype
- Source: https://archive.ics.uci.edu/dataset/31/covertype
- Why it looked promising: Medium-large integer tabular corpus adds a different integer-heavy shape.
- Failure class: operational_scope
- What happened: The dataset is feasible, but this pass focused on a smaller recipe batch. Covertype remains a good next exact-ID backfill after the first batch is validated.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Keep as a deferred backfill target.
- Retry conditions: Retry once the current exact-ID backfill batch is accepted.
