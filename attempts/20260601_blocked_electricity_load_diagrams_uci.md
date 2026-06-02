# electricity_load_diagrams_uci

- Date: 2026-06-01
- Status: blocked
- Candidate dataset: UCI ElectricityLoadDiagrams20112014
- Source: https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014
- Why it looked promising: Multi-series electricity loads are useful numeric time-series.
- Failure class: operational_scope
- What happened: The upstream text export is large and would require a dedicated heavy ingest pass. This registry sync pass prioritized smaller exact-ID backfills first.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Keep as a deferred backfill target.
- Retry conditions: Retry in a later large-timeseries pass with explicit raw-size budget.
