# COVID-19 Google Mobility Trends Float64

Domain: pandemic human mobility behavior — Google aggregated smartphone mobility percent change from baseline (retail & recreation, grocery & pharmacy, parks, transit stations, workplaces, residential). Distinct from:

- `citibike_2024_trip_geocoords_f64` (bike share operational trips geocoords)
- `opensky_states` (ADS-B aircraft positions)
- `jhu_covid19_*` (epidemiology confirmed/deaths counts, not mobility)
- `open_meteo_*` (weather model temperature/precipitation)
- `google_books_1gram_counts_2020_eng_u64` (book n-gram cultural counts)

Material: `https://storage.googleapis.com/covid19-open-data/v3/mobility.csv` (223MB CSV, GCS public bucket, allowlisted host — same infra as accepted `google_books_1gram_counts_2020_eng_u64`). Columns include location_key, date, and six mobility percent change float columns.

Natural record: one location-date mobility observation.

Primary series: 6 columns as float64 samples:
- `covid19_retail_and_recreation_f64`
- `covid19_grocery_and_pharmacy_f64`
- `covid19_parks_f64`
- `covid19_transit_stations_f64`
- `covid19_workplaces_f64`
- `covid19_residential_f64`

Each sample contains millions of values (median 4,032,314), total 24,556,604 values, 196MB, well above floor 10k / 100KB / median 1k, below 1GB cap.

License: CC BY 4.0 (COVID-19 Open Data).

Build: local-only after download, parses CSV DictReader, extracts six float columns, rejects non-finite, writes little-endian f64 bins preserving row order.

Verify: rejects constant, non-finite, checks floor.

Run:
```bash
bash staging/covid19_google_mobility_f64/download.sh
bash staging/covid19_google_mobility_f64/build.sh
bash staging/covid19_google_mobility_f64/verify.sh
```
