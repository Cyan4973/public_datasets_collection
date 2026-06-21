# USGS Daily Values Large

USGS NWIS daily-values time series, organized as **one family per physical parameter**,
with **one sample per gauge site** — the homogeneity policy's "many station-series of
the same physical quantity" consolidation.

- Source: https://waterservices.usgs.gov/nwis/dv/ (U.S. public-domain data)
- Local raw pages: `${DATA_DIR:-.data}/downloads/usgs_daily_values_large/pages/`

## Families & samples

Each parameter is a separate family (different unit/regime → never mixed):

| family | parameter | unit |
|---|---|---|
| `usgs_streamflow_cfs_f64` | 00060 | ft³/s |
| `usgs_gage_height_ft_f64` | 00065 | ft |
| `usgs_water_temp_c_f64` | 00010 | °C (only if ≥5 sites) |

- **A sample** = one gauge site's daily-mean series (float64), longest valid series for
  that site, **≥1000 days**, sentinel (-999999) days removed.
- **Samples/family** = number of qualifying sites (many — gathered across several states).
- A family is dropped if it has fewer than 5 sites.

## Scope

- states: `USGS_STATES` (default `co or ga ut ia`) — varied hydrology
- parameters: `USGS_PARAMS` (default `00060 00065 00010`)
- window: `USGS_START_DT`..`USGS_END_DT` (default 2019–2024); daily mean (`statCd=00003`)

Streamflow magnitudes span many orders across sites (small creeks to large rivers); this
is intentional and homogeneous — all are daily streamflow series of the same physical
quantity. Oversized/failed per-state queries are skipped.

## Run

```sh
bash datasets/usgs_daily_values_large/download.sh
bash datasets/usgs_daily_values_large/build.sh
bash datasets/usgs_daily_values_large/verify.sh
```

Tuning env vars: `USGS_STATES`, `USGS_PARAMS`, `USGS_START_DT`, `USGS_END_DT`, `USGS_MIN_DAYS`, `USGS_MIN_SAMPLES_PER_FAMILY`, `USGS_REQUEST_DELAY_SECONDS`. Logs under `${DATA_DIR:-.data}/logs/usgs_daily_values_large/`.
