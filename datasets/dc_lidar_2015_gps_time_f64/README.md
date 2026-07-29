# DC LiDAR 2015 GPS time — float64

This recipe extracts the native GPS-time attribute from three public District
of Columbia 2015 airborne-LiDAR LAS tiles. All selected files use LAS point
data record format 6, whose GPS time field is an IEEE-754 binary64 value at
byte offset 22 of every 30-byte point record.

The natural sample is one LAS tile's acquisition-order GPS-time stream. The
recipe copies those eight source bytes unchanged for every point; it does not
widen an integer timestamp or derive time from another field.

The same source tiles support the accepted uint8 classification recipe, but
this series has a different numerical character: high-resolution acquisition
time, mostly locally ordered with flight-line transitions.

Source: <https://registry.opendata.aws/dc-lidar-2015/>

## Run

```bash
bash datasets/dc_lidar_2015_gps_time_f64/download.sh
bash datasets/dc_lidar_2015_gps_time_f64/build.sh
bash datasets/dc_lidar_2015_gps_time_f64/verify.sh
```

The downloader first looks for the already-validated source tiles in the
accepted classification recipe's local cache. It hard-links them after exact
size and SHA-256 validation, avoiding a redundant 650 MB download. If that
cache is absent, it downloads the same three exact public S3 objects.
