# eurostat_youth_unemployment_monthly

- Date attempted: 2026-06-12
- Status: blocked
- Source URLs:
  - `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m?sex=T&age=Y15-24&unit=PC_ACT&geo=DE,FR,IT,ES,NL`
- Expected value:
  - Public labor-market time series from a legitimate macro source family.
- Failure reason:
  - The accepted recipe built zero-value sample files and should not have been admitted.
  - Current local output under `.data/index/eurostat_youth_unemployment_monthly/samples.jsonl` reports `0` values and `0` bytes.
  - The recipe needs rework against the real response shape before it can be reconsidered.
- Evidence:
  - `reports/accepted_recipe_audit.tsv`
  - `.data/index/eurostat_youth_unemployment_monthly/samples.jsonl`
  - `datasets/eurostat_youth_unemployment_monthly/build.sh` before removal
- Retry posture:
  - Worth retrying later, but only after revalidating the Eurostat payload shape and proving non-empty outputs in `staging/`.
