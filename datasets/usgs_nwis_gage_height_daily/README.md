# USGS NWIS Daily Gage Height

This recipe collects a curated subset of USGS NWIS daily gage-height
observations and converts selected numeric fields into raw numeric samples.

Selected scope:
- parameter code `00065` (gage height)
- years `2021` through `2023`
- sites:
  - `07374000`
- one output sample per site per series

Series emitted by `build.sh`:
- `usgs_gage_height_ft_f64` (`float64`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)

Notes:
- Source data comes from the USGS NWIS daily values JSON API.
- Downloads are chunked by site and calendar year with fixed date windows.
- `build.sh` preserves source observation order within each site-year response
  and concatenates years in ascending order for each site.
- For sites that expose multiple daily statistics, `build.sh` selects statistic
  code `00003` for parameter `00065`.
- Date component arrays are emitted only for rows with a parseable gage-height
  value so they align 1:1 with the value series.
- No padding, synthesis, interpolation, or quantization is applied.

Usage:

```sh
bash datasets/usgs_nwis_gage_height_daily/download.sh
bash datasets/usgs_nwis_gage_height_daily/build.sh
bash datasets/usgs_nwis_gage_height_daily/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/usgs_nwis_gage_height_daily/download_plan.tsv`
- `downloads/usgs_nwis_gage_height_daily/download_failures.tsv`
- `downloads/usgs_nwis_gage_height_daily/dv_<site>_<year>.json`
- `downloads/usgs_nwis_gage_height_daily/collection_checksums.sha256`
- `filtered/usgs_nwis_gage_height_daily/site_year_stats.tsv`
- `index/usgs_nwis_gage_height_daily/samples.jsonl`
- `logs/usgs_nwis_gage_height_daily/download.latest.log`
- `logs/usgs_nwis_gage_height_daily/build.latest.log`
- `logs/usgs_nwis_gage_height_daily/verify.latest.log`
- `samples/usgs_nwis_gage_height_daily/<series_id>/site_<site>.bin`

Logging:
- Every script writes timestamped logs under
  `${DATA_DIR:-.data}/logs/usgs_nwis_gage_height_daily/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent run.
- `download.sh` writes `download_failures.tsv` with one row per failed site-year
  fetch.

Sample index:
- `build.sh` writes
  `${DATA_DIR:-.data}/index/usgs_nwis_gage_height_daily/samples.jsonl`.
- The index contains one JSON object per sample file with the standard sample
  index fields.
