# JPL Small-Body Close Approaches

JPL/CNEOS close-approach data (CAD) over a multi-decade window, extracted into one numeric column sample per native field. (Supersedes the single-year `jpl_cad_2024`.)

- Source: https://ssd-api.jpl.nasa.gov/cad.api (NASA/JPL SSD/CNEOS)
- Scope: all small-body close approaches for each decade in `JPL_START_DECADE`..`JPL_END_DECADE` (default **1900–2099**), fetched one decade per page.
- Local raw pages: `${DATA_DIR:-.data}/downloads/jpl_close_approaches/pages/`

## Series (each a `table_column` sample, one value per close-approach row, float64)

| series_id | CAD field | meaning |
|---|---|---|
| `jpl_cad_jd` | `jd` | close-approach Julian date |
| `jpl_cad_dist` | `dist` | nominal distance (au) |
| `jpl_cad_dist_min` | `dist_min` | min 3σ distance (au) |
| `jpl_cad_dist_max` | `dist_max` | max 3σ distance (au) |
| `jpl_cad_v_rel` | `v_rel` | relative velocity (km/s) |
| `jpl_cad_v_inf` | `v_inf` | velocity vs massless body (km/s) |
| `jpl_cad_h` | `h` | absolute magnitude H |

Rows are de-duplicated by `(des, jd)`; malformed rows are dropped atomically so all columns stay equal length.

## Run

```sh
bash datasets/jpl_close_approaches/download.sh
bash datasets/jpl_close_approaches/build.sh
bash datasets/jpl_close_approaches/verify.sh
```

Tuning env vars: `JPL_START_DECADE`, `JPL_END_DECADE`, `JPL_MIN_RECORDS`, `JPL_REQUEST_DELAY_SECONDS`. Logs under `${DATA_DIR:-.data}/logs/jpl_close_approaches/`.
