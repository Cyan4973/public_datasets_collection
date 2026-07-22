# NOAA Storm Events Detail Numeric Fields 2024 (f64)

Accepted `float64` recipe for the NOAA/NCEI Storm Events 2024 details CSV.

The primary samples are decoded numeric CSV fields such as event coordinates,
meteorological magnitude, direct/indirect casualty counts, and property/crop
damage amounts. This is not gzip or CSV byte preservation.

## Run

```bash
bash datasets/noaa_stormevents_details_2024_f64/download.sh
bash datasets/noaa_stormevents_details_2024_f64/build.sh
bash datasets/noaa_stormevents_details_2024_f64/verify.sh
```

The script discovers the newest NOAA correction file for detail year `d2024`
from the official CSV directory. If NOAA changes the listing shape, set
`NOAA_STORMEVENTS_DETAILS_URL` to an exact
`StormEvents_details-ftp_v1.0_d2024_cYYYYMMDD.csv.gz` URL.

The accepted local run used `StormEvents_details-ftp_v1.0_d2024_c20260421.csv.gz`
and produced 11 primary float64 samples, 593,574 values, and 4,748,592 primary
bytes.
