# HSL GTFS Static Schedule Numeric

This recipe collects the public Helsinki Region Transport (HSL) GTFS static
schedule feed and emits only numeric schedule and geometry fields.

The material is transit timetable/network data. Natural samples are numeric
columns or small numeric matrices from GTFS tables in one published feed ZIP.
Route names, stop names, IDs, and other textual fields are not emitted.

## Numeric Families

- `stop_times_arrival_seconds_i32`: service-day arrival times converted from
  GTFS `HH:MM:SS` to seconds.
- `stop_times_departure_seconds_i32`: service-day departure times converted
  from GTFS `HH:MM:SS` to seconds.
- `stop_times_stop_sequence_u32`: native GTFS stop sequence numbers.
- `stop_times_shape_dist_traveled_f64`: optional stop-time distances when
  present.
- `shapes_lat_lon_f64`: shape point latitude/longitude pairs.
- `shapes_sequence_u32`: native GTFS shape point sequence numbers.
- `shapes_dist_traveled_f64`: optional shape distances when present.
- `stops_lat_lon_f64`: stop latitude/longitude pairs.
- `frequencies_start_end_headway_seconds_i32`: optional start/end/headway
  second triples when `frequencies.txt` is present.

## Usage

```bash
bash staging/hsl_gtfs_static_schedule_numeric/download.sh
bash staging/hsl_gtfs_static_schedule_numeric/build.sh
bash staging/hsl_gtfs_static_schedule_numeric/verify.sh
```

The default source is the HSL public GTFS ZIP. To test a pinned replacement ZIP
for the same material, set:

```bash
HSL_GTFS_URL=https://example.invalid/hsl.zip
```

The build step is local-only and reads `.data/downloads/hsl_gtfs_static_schedule_numeric/hsl_gtfs.zip`.
