# USGS NWIS Daily Specific Conductance

This recipe collects long daily specific-conductance observations from the USGS NWIS
daily values API and converts the selected numeric field into raw float64
samples.

Selected scope:
- parameter code `00095` (specific conductance)
- statistic code `00003` (mean daily value)
- default date window `2000-01-01` through `2024-12-31`
- default state-page scan:
  `az ca co fl ga ia ma md nc nd ny or ri sc tx ut va wa wi wy`
- one output sample per selected site
- only sites with at least `7000` parseable daily values by default

Series emitted by `build.sh`:
- `usgs_specific_conductance_f64` (`float64`, little-endian)

Default quality gates:
- `USGS_NWIS_SPECIFIC_CONDUCTANCE_STATES`
- `USGS_NWIS_SPECIFIC_CONDUCTANCE_MIN_VALUES_PER_SAMPLE=7000`
- `USGS_NWIS_SPECIFIC_CONDUCTANCE_MIN_SAMPLE_COUNT=20`
- `USGS_NWIS_SPECIFIC_CONDUCTANCE_MIN_TOTAL_VALUES=150000`
- `USGS_NWIS_SPECIFIC_CONDUCTANCE_MAX_SAMPLES=120`

Verified output from the repaired collection:
- `120` homogeneous site samples
- `984,131` float64 values
- `7,873,048` primary sample bytes
- sample value count range: `7,021` / `8,317.5` / `9,073` min/median/max
- state-page scan found `1,439` candidate site series and `140` long site series;
  the build kept the first `120` sorted by state and site number

Notes:
- Source data comes from the USGS NWIS daily values JSON API.
- `download.sh` fetches one daily-values page per configured state for
  parameter `00095`, statistic `00003`, and the fixed date window.
- `build.sh` keeps site time series that pass the per-sample value threshold,
  sorted by state and site number, with a deterministic maximum sample cap.
- Sites must expose statistic code `00003` for parameter `00095`; other daily
  statistic codes are rejected to keep the family homogeneous.
- When USGS returns multiple value wrappers for the same statistic, the scripts
  keep the single wrapper with the most parseable values rather than
  concatenating duplicate daily records.
- `build.sh` preserves source observation order from the USGS response.
- `verify.sh` rejects short, constant, malformed, or non-finite samples.
- No padding, synthesis, interpolation, or quantization is applied.

Usage:

```sh
bash datasets/usgs_nwis_specific_conductance_daily/download.sh
bash datasets/usgs_nwis_specific_conductance_daily/build.sh
bash datasets/usgs_nwis_specific_conductance_daily/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/usgs_nwis_specific_conductance_daily/selected_sites.tsv`
- `downloads/usgs_nwis_specific_conductance_daily/download_plan.tsv`
- `downloads/usgs_nwis_specific_conductance_daily/download_failures.tsv`
- `downloads/usgs_nwis_specific_conductance_daily/pages/usgs_00095_<state>.json`
- `downloads/usgs_nwis_specific_conductance_daily/collection_checksums.sha256`
- `filtered/usgs_nwis_specific_conductance_daily/site_stats.tsv`
- `filtered/usgs_nwis_specific_conductance_daily/quality_summary.json`
- `index/usgs_nwis_specific_conductance_daily/samples.jsonl`
- `logs/usgs_nwis_specific_conductance_daily/download.latest.log`
- `logs/usgs_nwis_specific_conductance_daily/build.latest.log`
- `logs/usgs_nwis_specific_conductance_daily/verify.latest.log`
- `samples/usgs_nwis_specific_conductance_daily/usgs_specific_conductance_f64/site_<site>.bin`

Logging:
- Every script writes timestamped logs under
  `${DATA_DIR:-.data}/logs/usgs_nwis_specific_conductance_daily/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent
  run.

Sample index:
- `build.sh` writes
  `${DATA_DIR:-.data}/index/usgs_nwis_specific_conductance_daily/samples.jsonl`.
- The index contains one JSON object per sample file with the standard sample
  index fields.
