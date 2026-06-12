# owid_renewables_share_energy_annual

- Date attempted: 2026-06-12
- Status: blocked
- Source URLs:
  - `https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv`
- Expected value:
  - Public annual energy-mix series from a legitimate climate/energy source family.
- Failure reason:
  - The accepted recipe built zero-value sample files and should not have been admitted.
  - Current local output under `.data/index/owid_renewables_share_energy_annual/samples.jsonl` reports `0` values and `0` bytes.
  - The recipe needs rework against the actual OWID column availability and selected country subset before it can be reconsidered.
- Evidence:
  - `reports/accepted_recipe_audit.tsv`
  - `.data/index/owid_renewables_share_energy_annual/samples.jsonl`
  - `datasets/owid_renewables_share_energy_annual/build.sh` before removal
- Retry posture:
  - Worth retrying later, but only after rebuilding it in `staging/` and proving non-empty outputs from a fresh download.
