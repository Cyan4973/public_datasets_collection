# Citi Bike 2024 Trip Geocoordinates

Accepted replacement for `citibike_2024_01_trip_geocoords_f64`, expanded from
one month to the full 2024 Citi Bike tripdata archive set.

The recipe downloads the 12 exact monthly ZIP archives from the official Citi
Bike S3 tripdata bucket, validates that each ZIP contains CSV tripdata members
with the required geocoordinate columns, and emits native trip-level
latitude/longitude columns as little-endian float64 arrays.

Natural sample boundary: one provider CSV member table column. Some monthly
archives contain more than one CSV member, and those members remain separate
samples.

Run:

```bash
bash datasets/citibike_2024_trip_geocoords_f64/download.sh
bash datasets/citibike_2024_trip_geocoords_f64/build.sh
bash datasets/citibike_2024_trip_geocoords_f64/verify.sh
```

Use `DRY_RUN=1` to inspect the 12 exact URLs without fetching. If the archives
are already present locally, set `CITIBIKE_ARCHIVES_DIR=/path/to/zips` and the
download script will copy and validate them instead of fetching.

The normal primary output cap is treated as a soft 1 GB warning for this
full-year expansion. The verification path records and prints a warning above
1,000,000,000 primary bytes, and uses a 2,000,000,000-byte hard guard to reject
unexpectedly large output.

Material state from the validated local build:

- source archives: 12
- source bytes: 8,660,856,550
- CSV member samples per series: 50
- retained trip rows: 44,165,848
- skipped rows: 137,361
- primary samples: 200
- primary values: 176,663,392
- primary bytes: 1,413,307,136
- median primary sample values: 995,688.5
- size status: above 1 GB soft warning, below 2 GB hard guard
