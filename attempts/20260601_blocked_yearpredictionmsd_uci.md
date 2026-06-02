# yearpredictionmsd_uci

- Date: 2026-06-01
- Status: blocked
- Candidate dataset: UCI YearPredictionMSD
- Source: https://archive.ics.uci.edu/dataset/203/yearpredictionmsd
- Why it looked promising: Large real-valued music feature corpus with useful dense numeric structure.
- Failure class: operational_scope
- What happened: The upstream dataset is public and on-scope, but the raw and emitted footprint are materially larger than the smaller exact-ID imports prioritized in this sync pass.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Keep as a deferred backfill target rather than fabricating a partial recipe now.
- Retry conditions: Retry in a later large-dataset pass with explicit size budget and sharding review.
