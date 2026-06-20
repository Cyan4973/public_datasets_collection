# NASA DONKI Solar Flares

NASA DONKI solar flare events over a multi-year window, extracted into one numeric column sample per native or parsed flare field.

- Source: https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/FLR (NASA CCMC DONKI, no API key)
- Scope: all solar flare events for each calendar year in `DONKI_START_YEAR`..`DONKI_END_YEAR` (default **2010–2026**, the full DONKI archive), fetched one year per page.
- Local raw pages: `${DATA_DIR:-.data}/downloads/nasa_donki_flr/pages/`

## Series (each a `table_column` sample, one value per flare event)

| series_id | source | type |
|---|---|---|
| `donki_flr_begin_epoch_u32` | `beginTime` → epoch seconds | uint32 |
| `donki_flr_rise_seconds_u32` | `peakTime - beginTime` | uint32 |
| `donki_flr_decay_seconds_u32` | `endTime - peakTime` | uint32 |
| `donki_flr_active_region_u32` | `activeRegionNum` (else 0) | uint32 |
| `donki_flr_peak_flux_f32` | `classType` → GOES peak flux (W/m²) | float32 |
| `donki_flr_source_lat_f32` | `sourceLocation` latitude (N+) | float32 |
| `donki_flr_source_lon_f32` | `sourceLocation` longitude (E+) | float32 |

`classType` (e.g. `M2.3`) decodes to peak flux as `mantissa × decade` (A=1e-8 … X=1e-4). `sourceLocation` (e.g. `N03E70`) parses to signed heliographic lat/lon. Flares with unparseable required fields or negative durations are dropped atomically; events are de-duplicated by `flrID`.

## Run

```sh
bash datasets/nasa_donki_flr/download.sh
bash datasets/nasa_donki_flr/build.sh
bash datasets/nasa_donki_flr/verify.sh
```

Tuning env vars: `DONKI_START_YEAR`, `DONKI_END_YEAR`, `DONKI_MIN_RECORDS`, `DONKI_REQUEST_DELAY_SECONDS`. Logs under `${DATA_DIR:-.data}/logs/nasa_donki_flr/`.
