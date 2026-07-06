# USGS NWIS Daily Gage Height

This recipe collects long daily gage-height observations from the USGS NWIS
daily values API and converts the selected numeric field into raw float64
samples.

Selected scope:
- parameter code `00065` (gage height)
- default date window `2000-01-01` through `2024-12-31`
- active US stream sites discovered from the NWIS site inventory
- one output sample per selected site
- only sites with at least `7000` parseable daily values by default

Series emitted by `build.sh`:
- `usgs_gage_height_ft_f64` (`float64`, little-endian)

Default quality gates:
- `USGS_NWIS_GAGE_HEIGHT_TARGET_SITES=32`
- `USGS_NWIS_GAGE_HEIGHT_TARGET_CANDIDATES=500`
- `USGS_NWIS_GAGE_HEIGHT_MIN_VALUES_PER_SAMPLE=7000`
- `USGS_NWIS_GAGE_HEIGHT_MIN_SAMPLE_COUNT=20`
- `USGS_NWIS_GAGE_HEIGHT_MIN_TOTAL_VALUES=150000`

Verified output from the repaired collection:
- `30` homogeneous site samples
- `262068` float64 values
- `2096544` primary sample bytes

Notes:
- Source data comes from the USGS NWIS daily values JSON API.
- `download.sh` first downloads active stream-site inventory files by state,
  then probes candidate sites for long parameter-`00065` daily records.
- Candidate sites are round-robin selected across states to avoid concentrating
  the collection in one region.
- Sites below the per-sample value threshold are rejected and recorded in
  `candidate_rejections.tsv`.
- Sites must expose statistic code `00003` for parameter `00065`; other daily
  statistic codes are rejected to keep the family homogeneous.
- `build.sh` preserves source observation order from the USGS response.
- No padding, synthesis, interpolation, or quantization is applied.

Usage:

```sh
bash datasets/usgs_nwis_gage_height_daily/download.sh
bash datasets/usgs_nwis_gage_height_daily/build.sh
bash datasets/usgs_nwis_gage_height_daily/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/usgs_nwis_gage_height_daily/state_inventory_plan.tsv`
- `downloads/usgs_nwis_gage_height_daily/site_inventory/site_inventory_<state>.txt`
- `downloads/usgs_nwis_gage_height_daily/candidate_sites.tsv`
- `downloads/usgs_nwis_gage_height_daily/selected_sites.tsv`
- `downloads/usgs_nwis_gage_height_daily/candidate_rejections.tsv`
- `downloads/usgs_nwis_gage_height_daily/download_plan.tsv`
- `downloads/usgs_nwis_gage_height_daily/download_failures.tsv`
- `downloads/usgs_nwis_gage_height_daily/dv_<site>.json`
- `downloads/usgs_nwis_gage_height_daily/collection_checksums.sha256`
- `filtered/usgs_nwis_gage_height_daily/site_stats.tsv`
- `filtered/usgs_nwis_gage_height_daily/quality_summary.json`
- `index/usgs_nwis_gage_height_daily/samples.jsonl`
- `logs/usgs_nwis_gage_height_daily/download.latest.log`
- `logs/usgs_nwis_gage_height_daily/build.latest.log`
- `logs/usgs_nwis_gage_height_daily/verify.latest.log`
- `samples/usgs_nwis_gage_height_daily/usgs_gage_height_ft_f64/site_<site>.bin`

Logging:
- Every script writes timestamped logs under
  `${DATA_DIR:-.data}/logs/usgs_nwis_gage_height_daily/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent
  run.

Sample index:
- `build.sh` writes
  `${DATA_DIR:-.data}/index/usgs_nwis_gage_height_daily/samples.jsonl`.
- The index contains one JSON object per sample file with the standard sample
  index fields.
