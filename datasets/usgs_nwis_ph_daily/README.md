# USGS NWIS Daily pH

This recipe collects long daily pH observations from the USGS NWIS
daily values API and converts the selected numeric field into raw float64
samples.

Selected scope:
- parameter code `00400` (pH)
- statistic code `00003` (mean daily value)
- default date window `1980-01-01` through `2024-12-31`
- default state-page scan:
  `al ak az ar ca co ct de fl ga id il in ia ks ky la me md ma mi mn ms mo mt
  ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy`
- one output sample per selected site
- only sites with at least `3000` parseable daily values by default

Series emitted by `build.sh`:
- `usgs_ph_f64` (`float64`, little-endian)

Default quality gates:
- `USGS_NWIS_PH_STATES`
- `USGS_NWIS_PH_MIN_VALUES_PER_SAMPLE=3000`
- `USGS_NWIS_PH_MIN_SAMPLE_COUNT=20`
- `USGS_NWIS_PH_MIN_TOTAL_VALUES=150000`
- `USGS_NWIS_PH_MAX_SAMPLES=200`

Verified output from the repaired collection:
- `36` homogeneous site samples
- `202,184` float64 values
- `1,617,472` primary sample bytes
- sample value count range: `3,046` / `4,561.5` / `13,793` min/median/max
- state-page scan found `206` candidate site series and `36` selected site
  series above the default threshold
- accepted samples come from `al`, `de`, `ga`, `ks`, `me`, `nc`, `oh`, `pa`,
  `sc`, and `tx`
- one natural sample per site; no fixed-size sharding or synthetic splitting is
  applied

Scarcity note:
- The stricter `7000`-value threshold used for other repaired USGS daily
  datasets found only `8` pH site series across the 1980-2024 nationwide scan.
- The `5000`-value threshold found only `17` site series, below the default
  sample-count gate.
- The default `3000` threshold is an explicit pH-specific compromise that keeps
  natural multi-year site samples while still clearing the aggregate quality
  gates.

Notes:
- Source data comes from the USGS NWIS daily values JSON API.
- `download.sh` fetches one daily-values page per configured state for
  parameter `00400`, statistic `00003`, and the fixed date window.
- `build.sh` keeps site time series that pass the per-sample value threshold,
  sorted by state and site number, with a deterministic maximum sample cap.
- Sites must expose statistic code `00003` for parameter `00400`; other daily
  statistic codes are rejected to keep the family homogeneous.
- When USGS returns multiple value wrappers for the same statistic, the scripts
  keep the single wrapper with the most parseable values rather than
  concatenating duplicate daily records.
- `build.sh` preserves source observation order from the USGS response.
- `verify.sh` rejects short, constant, malformed, non-finite, or out-of-range
  pH samples.
- No padding, synthesis, interpolation, or quantization is applied.

Usage:

```sh
bash datasets/usgs_nwis_ph_daily/download.sh
bash datasets/usgs_nwis_ph_daily/build.sh
bash datasets/usgs_nwis_ph_daily/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/usgs_nwis_ph_daily/selected_sites.tsv`
- `downloads/usgs_nwis_ph_daily/download_plan.tsv`
- `downloads/usgs_nwis_ph_daily/download_failures.tsv`
- `downloads/usgs_nwis_ph_daily/pages/usgs_00400_<state>.json`
- `downloads/usgs_nwis_ph_daily/collection_checksums.sha256`
- `filtered/usgs_nwis_ph_daily/site_stats.tsv`
- `filtered/usgs_nwis_ph_daily/quality_summary.json`
- `index/usgs_nwis_ph_daily/samples.jsonl`
- `logs/usgs_nwis_ph_daily/download.latest.log`
- `logs/usgs_nwis_ph_daily/build.latest.log`
- `logs/usgs_nwis_ph_daily/verify.latest.log`
- `samples/usgs_nwis_ph_daily/usgs_ph_f64/<state>_<site>_n<values>.bin`

Logging:
- Every script writes timestamped logs under
  `${DATA_DIR:-.data}/logs/usgs_nwis_ph_daily/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent
  run.

Sample index:
- `build.sh` writes
  `${DATA_DIR:-.data}/index/usgs_nwis_ph_daily/samples.jsonl`.
- The index contains one JSON object per sample file with the standard sample
  index fields.
