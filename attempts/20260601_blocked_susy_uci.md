# susy_uci

- Date: 2026-06-01
- Status: blocked
- Candidate dataset: UCI SUSY
- Source: https://archive.ics.uci.edu/dataset/279/susy
- Why it looked promising: Very large dense numeric corpus with useful compression diversity.
- Failure class: operational_scope
- What happened: The dataset is public and relevant, but five-million-row ingestion is outside the scope of this exact-ID sync pass.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Keep as a deferred backfill target.
- Retry conditions: Retry in a future large-dataset pass with explicit resource budget.
