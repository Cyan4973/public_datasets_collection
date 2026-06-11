# USGS NWIS Daily Streamflow

This recipe collects a curated subset of USGS NWIS daily streamflow observations
and converts selected numeric fields into raw numeric samples.

Selected scope:
- parameter code `00060` (discharge, cubic feet per second)
- years `2021` through `2023`
- 32 geographically diverse stream sites across the contiguous United States
- one output sample per site per series

| Site ID    | Description                              | Region              |
|------------|------------------------------------------|---------------------|
| `01100000` | Merrimack R at Lawrence MA               | Northeast           |
| `01372500` | Hudson R at Poughkeepsie NY              | Northeast           |
| `01463500` | Delaware R at Trenton NJ                 | Northeast           |
| `01481500` | Brandywine Ck at Wilmington DE           | Mid-Atlantic        |
| `01578310` | Susquehanna R at Conowingo MD            | Mid-Atlantic        |
| `01594440` | Patuxent R at Bowie MD                   | Mid-Atlantic        |
| `01646500` | Potomac R at Little Falls MD             | Mid-Atlantic        |
| `02087500` | Neuse R near Kinston NC                  | Southeast           |
| `02169500` | Congaree R near Columbia SC              | Southeast           |
| `02215500` | Oconee R at Milledgeville GA             | Southeast           |
| `02335000` | Chattahoochee R at Atlanta GA            | Southeast           |
| `02342500` | Apalachicola R at Chattahoochee FL       | Southeast           |
| `04085427` | Fox R at Green Bay WI                    | Midwest             |
| `04193500` | Maumee R at Waterville OH                | Midwest             |
| `05288500` | Mississippi R at Minneapolis MN          | Midwest             |
| `05420500` | Mississippi R at Clinton IA              | Midwest             |
| `05587450` | Illinois R at Valley City IL             | Midwest             |
| `06805500` | Platte R at Ashland NE                   | Great Plains        |
| `06892350` | Kansas R at DeSoto KS                    | Great Plains        |
| `06934500` | Missouri R at Hermann MO                 | Midwest             |
| `07022000` | Mississippi R at Thebes IL               | South               |
| `07144200` | Arkansas R at Wichita KS                 | Great Plains        |
| `07374000` | Mississippi R at Baton Rouge LA          | South               |
| `07381490` | Atchafalaya R at Melville LA             | South               |
| `08158000` | Colorado R at Austin TX                  | South / Texas       |
| `09085000` | Colorado R near Dotsero CO               | Mountain West       |
| `09163500` | Colorado R near Colorado-Utah line       | Mountain West       |
| `11447650` | Sacramento R at Sacramento CA            | West Coast          |
| `12114500` | Green R at Auburn WA                     | Pacific Northwest   |
| `13011900` | Snake R near Moran WY                    | Mountain West       |
| `14048000` | Deschutes R at Moody OR                  | Pacific Northwest   |
| `14211720` | Willamette R at Portland OR              | Pacific Northwest   |

Series emitted by `build.sh`:
- `usgs_discharge_cfs_f64` (`float64`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)
- `obs_month_u8` (`uint8`)
- `obs_day_u8` (`uint8`)

Notes:
- Source data comes from the USGS NWIS daily values JSON API.
- Downloads are chunked by site and calendar year with fixed UTC date windows.
- `build.sh` preserves source observation order within each site-year response and
  concatenates years in ascending order for each site.
- For sites that expose multiple daily statistics, `build.sh` selects statistic
  code `00003` (`Mean`) for parameter `00060`.
- `obs_year_u16`, `obs_month_u8`, and `obs_day_u8` are emitted only for rows
  with a parseable discharge value so the date arrays align 1:1 with discharge.
- No padding, synthesis, interpolation, or quantization is applied.

Usage:

```sh
bash datasets/usgs_nwis_streamflow_daily/download.sh
bash datasets/usgs_nwis_streamflow_daily/build.sh
bash datasets/usgs_nwis_streamflow_daily/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/usgs_nwis_streamflow_daily/download_plan.tsv`
- `downloads/usgs_nwis_streamflow_daily/download_failures.tsv`
- `downloads/usgs_nwis_streamflow_daily/dv_<site>_<year>.json`
- `downloads/usgs_nwis_streamflow_daily/collection_checksums.sha256`
- `filtered/usgs_nwis_streamflow_daily/site_year_stats.tsv`
- `index/usgs_nwis_streamflow_daily/samples.jsonl`
- `logs/usgs_nwis_streamflow_daily/download.latest.log`
- `logs/usgs_nwis_streamflow_daily/build.latest.log`
- `logs/usgs_nwis_streamflow_daily/verify.latest.log`
- `samples/usgs_nwis_streamflow_daily/<series_id>/site_<site>.bin`

Logging:
- Every script writes timestamped logs under
  `${DATA_DIR:-.data}/logs/usgs_nwis_streamflow_daily/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent run.
- `download.sh` writes `download_failures.tsv` with one row per failed site-year
  fetch.

Sample index:
- `build.sh` writes
  `${DATA_DIR:-.data}/index/usgs_nwis_streamflow_daily/samples.jsonl`.
- The index contains one JSON object per sample file with `dataset_id`,
  `series_id`, `sample_path`, `numeric_kind`, `bit_width`, `endianness`,
  `element_size_bytes`, `sample_size_bytes`, and `value_count`.
