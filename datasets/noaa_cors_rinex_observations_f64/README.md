# NOAA CORS RINEX GNSS Observations (float64)

Accepted decoder recipe for raw satellite-navigation observations from the NOAA
Continuously Operating Reference Stations network.

It decodes actual RINEX observation fields—not gzip or RINEX container bytes—
into four unit-coherent families:

- pseudorange (C*/P*) in meters
- carrier phase (L*) in cycles
- signal strength (S*) in the receiver's RINEX convention

Each natural sample is one observation code from one station-day file. Samples
below 1,000 values are reported and excluded before global acceptance floors are
checked.

## Run

```bash
bash staging/noaa_cors_rinex_observations_f64/download.sh
bash staging/noaa_cors_rinex_observations_f64/build.sh
bash staging/noaa_cors_rinex_observations_f64/verify.sh
```

The downloader defaults to a sorted bounded selection under the fixed NOAA CORS
AWS prefix `rinex/2024/001/`. If bucket discovery changes, provide one exact
HTTPS object URL per line:

```bash
RINEX_URLS_FILE=/path/to/rinex_urls.txt \
  bash staging/noaa_cors_rinex_observations_f64/download.sh
```

## Realized validation

The user-run download selected twelve RINEX 2.11 station-day files totaling
24,974,679 bytes. Build and independent verification retained 115 natural
samples with 4,574,236 float64 values (36,593,888 bytes); median sample length
was 32,648 values. The realized source exposed pseudorange, carrier phase, and
signal strength families; seven sub-floor station/code streams were excluded.
