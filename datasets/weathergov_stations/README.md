# Weather.gov Stations

This recipe collects the public weather.gov observation-station catalog and
emits homogeneous numeric station-location fields.

The previous accepted recipe fetched only the first API page. This version
follows the weather.gov pagination cursor up to a bounded feature cap so the
station catalog can pass the repository acceptance floors without changing the
natural material.

## Numeric Families

- `weathergov_station_lon_f64`: station longitude values in source order.
- `weathergov_station_lat_f64`: station latitude values in source order.
- `weathergov_station_elevation_m_f32`: station elevation in meters.

Each family is a separate homogeneous column. Textual identifiers, names,
URLs, time zones, and geometry objects are not emitted.

## Usage

```bash
bash datasets/weathergov_stations/download.sh
bash datasets/weathergov_stations/build.sh
bash datasets/weathergov_stations/verify.sh
```

The download is bounded by `WEATHERGOV_MAX_FEATURES` and
`WEATHERGOV_MAX_PAGES`. The defaults are intended to exhaust the public station
catalog while staying operationally small.
