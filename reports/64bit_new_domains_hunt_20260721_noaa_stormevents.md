# 64-Bit New-Domain Hunt: NOAA Storm Events Details

## Recommendation

Run the staged recipe `noaa_stormevents_details_2024_f64`.

```bash
bash staging/noaa_stormevents_details_2024_f64/download.sh
```

## Why This Adds New Territory

- Domain: official severe-weather event reports and impacts.
- Primary target: decoded NOAA Storm Events detail-table numeric fields written
  as `float64`.
- Difference from accepted datasets: the collection already has weather station
  observations, radar bins, hydrology gauges, and geospatial rasters. Storm
  Events detail records are human/operational event reports with event
  coordinates, meteorological magnitude, casualties, and damage amounts.
- Natural sample: one 2024 source detail-table field, preserving event row order
  after field-local blank skips.

## Materiality

The source is the NOAA/NCEI gzip CSV for detail year `d2024`:

`StormEvents_details-ftp_v1.0_d2024_cYYYYMMDD.csv.gz`

NOAA updates the correction-date suffix over time. The staged downloader now
discovers the newest `d2024` details file from the official CSV directory and
keeps exact fallback URLs for recent correction dates.

The selected fields are:

- `BEGIN_LAT`, `BEGIN_LON`, `END_LAT`, `END_LON`
- `MAGNITUDE`
- `INJURIES_DIRECT`, `INJURIES_INDIRECT`
- `DEATHS_DIRECT`, `DEATHS_INDIRECT`
- `DAMAGE_PROPERTY`, `DAMAGE_CROPS`

Each retained field should have thousands to tens of thousands of records, so
the recipe is expected to clear the floor without concatenating unrelated
records or using compressed file bytes.

## Guardrails

The download script rejects HTML/error payloads, malformed gzip, missing
required numeric columns, and too few detail rows. The build parses CSV values
only, writes one homogeneous `float64` sample per source field, and records the
exact decoded `source_field` in the sample index.

## Outcome

Accepted and promoted to `datasets/noaa_stormevents_details_2024_f64`.

- Downloaded source: `StormEvents_details-ftp_v1.0_d2024_c20260421.csv.gz`.
- Source rows: 69,801.
- Source bytes: 12,693,422.
- Decoded primary output: 11 float64 samples, 593,574 values, 4,748,592 bytes.
- Median primary sample length: 54,388 values.
- Validation: all selected samples are decoded CSV numeric fields, all are
  nonconstant, and no gzip/CSV file bytes are primary data.
