# NASA DONKI Coronal Mass Ejections

NASA DONKI CME events over a multi-year window, extracted into one numeric column sample per native CME-analysis field.

- Source: https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/CME (NASA CCMC DONKI)
- Scope: all CME events for each calendar year in `DONKI_START_YEAR`..`DONKI_END_YEAR` (default **2020–2024**), fetched one year per page. The 2024-only window was too thin for the floor; widening years adds real measurements (the dataset id is already generic).
- Local raw pages: `${DATA_DIR:-.data}/downloads/nasa_donki_cme/pages/`

## Series (each a `table_column` sample, one value per CME event)

Per event the **most-accurate** analysis is used (else the first), and these fields are extracted:

| series_id | field | type |
|---|---|---|
| `donki_cme_latitude_f32` | analysis `latitude` (deg) | float32 |
| `donki_cme_longitude_f32` | analysis `longitude` (deg) | float32 |
| `donki_cme_half_angle_f32` | analysis `halfAngle` (deg) | float32 |
| `donki_cme_speed_f32` | analysis `speed` (km/s) | float32 |
| `donki_cme_start_epoch_u32` | `startTime` → epoch seconds | uint32 |

Events missing any required field (or with no analysis) are dropped atomically so all columns stay equal length; events are de-duplicated by `activityID`.

## Run

```sh
bash datasets/nasa_donki_cme/download.sh
bash datasets/nasa_donki_cme/build.sh
bash datasets/nasa_donki_cme/verify.sh
```

Tuning env vars: `DONKI_START_YEAR`, `DONKI_END_YEAR`, `DONKI_MIN_RECORDS`, `DONKI_REQUEST_DELAY_SECONDS`. Logs under `${DATA_DIR:-.data}/logs/nasa_donki_cme/`.
