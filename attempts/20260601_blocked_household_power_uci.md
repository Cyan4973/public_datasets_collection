# household_power_uci

- Date: 2026-06-01
- Status: blocked
- Candidate dataset: UCI Individual household electric power consumption
- Source: https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption
- Why it looked promising: Real long-horizon household energy series with strong numeric structure.
- Failure class: operational_scope
- What happened: The external reference is valid, but this pass prioritized a smaller initial backfill batch. This import has multi-million-row parsing cost and remains worth doing after the current exact-ID backfills land.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Do not treat as rejected; keep as an explicit deferred backfill target.
- Retry conditions: Retry once the current exact-ID UCI backfill batch is accepted and there is budget for another large-row CSV recipe.
