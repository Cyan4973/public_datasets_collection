# USGS NWIS Daily Streamflow

This recipe collects long daily streamflow observations from the USGS NWIS
daily values API and converts the selected numeric field into raw float64
samples.

Selected scope:
- parameter code `00060` (discharge, cubic feet per second)
- statistic code `00003` (mean daily value)
- default date window `2000-01-01` through `2024-12-31`
- active US stream sites discovered from the NWIS site inventory
- one output sample per selected site
- only sites with at least `7000` parseable daily values by default

Series emitted by `build.sh`:
- `usgs_discharge_cfs_f64` (`float64`, little-endian)

Default quality gates:
- `USGS_NWIS_STREAMFLOW_TARGET_SITES=40`
- `USGS_NWIS_STREAMFLOW_TARGET_CANDIDATES=500`
- `USGS_NWIS_STREAMFLOW_MIN_VALUES_PER_SAMPLE=7000`
- `USGS_NWIS_STREAMFLOW_MIN_SAMPLE_COUNT=20`
- `USGS_NWIS_STREAMFLOW_MIN_TOTAL_VALUES=150000`

Verified output from the repaired collection:
- `40` homogeneous site samples
- `362420` float64 values
- `2899360` primary sample bytes

Notes:
- Source data comes from the USGS NWIS daily values JSON API.
- `download.sh` first downloads active stream-site inventory files by state,
  then probes candidate sites for long parameter-`00060` daily records.
- Candidate sites are round-robin selected across states to avoid concentrating
  the collection in one region.
- Sites below the per-sample value threshold are rejected and recorded in
  `candidate_rejections.tsv`.
- Sites must expose statistic code `00003` for parameter `00060`; other daily
  statistic codes are rejected to keep the family homogeneous.
- When USGS returns multiple value wrappers for the same statistic, the scripts
  keep the single wrapper with the most parseable values rather than
  concatenating duplicate daily records.
- `build.sh` preserves source observation order from the USGS response.
- No padding, synthesis, interpolation, or quantization is applied.

Usage:

```sh
bash datasets/usgs_nwis_streamflow_daily/download.sh
bash datasets/usgs_nwis_streamflow_daily/build.sh
bash datasets/usgs_nwis_streamflow_daily/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/usgs_nwis_streamflow_daily/state_inventory_plan.tsv`
- `downloads/usgs_nwis_streamflow_daily/site_inventory/site_inventory_<state>.txt`
- `downloads/usgs_nwis_streamflow_daily/candidate_sites.tsv`
- `downloads/usgs_nwis_streamflow_daily/selected_sites.tsv`
- `downloads/usgs_nwis_streamflow_daily/candidate_rejections.tsv`
- `downloads/usgs_nwis_streamflow_daily/download_plan.tsv`
- `downloads/usgs_nwis_streamflow_daily/download_failures.tsv`
- `downloads/usgs_nwis_streamflow_daily/dv_<site>.json`
- `downloads/usgs_nwis_streamflow_daily/collection_checksums.sha256`
- `filtered/usgs_nwis_streamflow_daily/site_stats.tsv`
- `filtered/usgs_nwis_streamflow_daily/quality_summary.json`
- `index/usgs_nwis_streamflow_daily/samples.jsonl`
- `logs/usgs_nwis_streamflow_daily/download.latest.log`
- `logs/usgs_nwis_streamflow_daily/build.latest.log`
- `logs/usgs_nwis_streamflow_daily/verify.latest.log`
- `samples/usgs_nwis_streamflow_daily/usgs_discharge_cfs_f64/site_<site>.bin`

Logging:
- Every script writes timestamped logs under
  `${DATA_DIR:-.data}/logs/usgs_nwis_streamflow_daily/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent
  run.

Sample index:
- `build.sh` writes
  `${DATA_DIR:-.data}/index/usgs_nwis_streamflow_daily/samples.jsonl`.
- The index contains one JSON object per sample file with the standard sample
  index fields.
