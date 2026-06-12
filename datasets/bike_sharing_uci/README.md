# UCI Bike Sharing

Hourly bike-sharing records (`hour.csv`, 17,379 hourly rows, Washington DC, 2011–2012).
Only the **real measured columns** are emitted; calendar/calendar-derived index
fields are excluded as low-value filler.

Retained series (one sample per column, `hour.bin`):

| series | column | width | notes |
|--------|--------|-------|-------|
| `bike_temp` | temp | f32 | normalized temperature |
| `bike_atemp` | atemp | f32 | normalized feeling temperature |
| `bike_hum` | hum | f32 | normalized humidity |
| `bike_windspeed` | windspeed | f32 | normalized wind speed |
| `bike_weathersit` | weathersit | u8 | observed weather code (1–4) |
| `bike_casual` | casual | u16 | casual-user rentals/hour |
| `bike_registered` | registered | u16 | registered-user rentals/hour |
| `bike_cnt` | cnt | u16 | total rentals/hour |

Excluded columns:
- `instant` (record index), `dteday` (date string)
- `season`, `yr`, `mnth`, `hr`, `weekday` (calendar / time index)
- `holiday`, `workingday` (calendar-derived flags)

Widths are chosen so every value fits its target format (counts max 977 → u16;
weathersit 1–4 → u8; weather values are normalized floats → f32). Integer columns
are range-checked at build and verify; malformed or out-of-range rows are fatal.

Usage:
```sh
bash datasets/bike_sharing_uci/download.sh
bash datasets/bike_sharing_uci/build.sh
bash datasets/bike_sharing_uci/verify.sh
```
