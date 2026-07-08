# USGS NWIS Daily Dissolved Oxygen

This recipe collects long daily dissolved-oxygen observations from the USGS NWIS
daily values API and converts the selected numeric field into raw float64
samples.

Selected scope:
- parameter code `00300` (dissolved oxygen)
- statistic code `00003` (mean daily value)
- default date window `2000-01-01` through `2024-12-31`
- default state-page scan:
  `al ak az ca co fl ga ia in ma md mi nc nd ne ny or pa ri sc tx ut va wa wi wy`
- one output sample per selected site
- only sites with at least `7000` parseable daily values by default

Series emitted by `build.sh`:
- `usgs_dissolved_oxygen_f64` (`float64`, little-endian)

Default quality gates:
- `USGS_NWIS_DISSOLVED_OXYGEN_STATES`
- `USGS_NWIS_DISSOLVED_OXYGEN_MIN_VALUES_PER_SAMPLE=7000`
- `USGS_NWIS_DISSOLVED_OXYGEN_MIN_SAMPLE_COUNT=20`
- `USGS_NWIS_DISSOLVED_OXYGEN_MIN_TOTAL_VALUES=150000`
- `USGS_NWIS_DISSOLVED_OXYGEN_MAX_SAMPLES=120`

Verified output from the repaired collection:
- `85` homogeneous site samples
- `700,423` float64 values
- `5,603,384` primary sample bytes
- sample value count range: `7,096` / `8,398` / `8,996` min/median/max
- state-page scan found `944` candidate site series and `85` long site series
- accepted samples come from `al`, `co`, `ga`, `mi`, `nc`, `nd`, `or`,
  `sc`, `tx`, `ut`, and `wi`
- one natural sample per site; no fixed-size sharding or synthetic splitting is
  applied

Notes:
- Source data comes from the USGS NWIS daily values JSON API.
- `download.sh` fetches one daily-values page per configured state for
  parameter `00300`, statistic `00003`, and the fixed date window.
- `build.sh` keeps site time series that pass the per-sample value threshold,
  sorted by state and site number, with a deterministic maximum sample cap.
- Sites must expose statistic code `00003` for parameter `00300`; other daily
  statistic codes are rejected to keep the family homogeneous.
- When USGS returns multiple value wrappers for the same statistic, the scripts
  keep the single wrapper with the most parseable values rather than
  concatenating duplicate daily records.
- `build.sh` preserves source observation order from the USGS response.
- `verify.sh` rejects short, constant, malformed, or non-finite samples.
- No padding, synthesis, interpolation, or quantization is applied.

Usage:

```sh
bash datasets/usgs_nwis_dissolved_oxygen_daily/download.sh
bash datasets/usgs_nwis_dissolved_oxygen_daily/build.sh
bash datasets/usgs_nwis_dissolved_oxygen_daily/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/usgs_nwis_dissolved_oxygen_daily/selected_sites.tsv`
- `downloads/usgs_nwis_dissolved_oxygen_daily/download_plan.tsv`
- `downloads/usgs_nwis_dissolved_oxygen_daily/download_failures.tsv`
- `downloads/usgs_nwis_dissolved_oxygen_daily/pages/usgs_00300_<state>.json`
- `downloads/usgs_nwis_dissolved_oxygen_daily/collection_checksums.sha256`
- `filtered/usgs_nwis_dissolved_oxygen_daily/site_stats.tsv`
- `filtered/usgs_nwis_dissolved_oxygen_daily/quality_summary.json`
- `index/usgs_nwis_dissolved_oxygen_daily/samples.jsonl`
- `logs/usgs_nwis_dissolved_oxygen_daily/download.latest.log`
- `logs/usgs_nwis_dissolved_oxygen_daily/build.latest.log`
- `logs/usgs_nwis_dissolved_oxygen_daily/verify.latest.log`
- `samples/usgs_nwis_dissolved_oxygen_daily/usgs_dissolved_oxygen_f64/<state>_<site>_n<values>.bin`

Logging:
- Every script writes timestamped logs under
  `${DATA_DIR:-.data}/logs/usgs_nwis_dissolved_oxygen_daily/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent
  run.

Sample index:
- `build.sh` writes
  `${DATA_DIR:-.data}/index/usgs_nwis_dissolved_oxygen_daily/samples.jsonl`.
- The index contains one JSON object per sample file with the standard sample
  index fields.
