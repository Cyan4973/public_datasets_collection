# 8-Bit New-Domain Hunt: NOAA/NSIDC Sea-Ice Concentration

## Recommendation

Run the staged recipe `noaa_cdr_sea_ice_concentration_u8`.

## Why This Adds New Territory

- Domain: cryosphere remote-sensing climate records.
- Shape: one raw byte-valued polar sea-ice concentration grid per daily NetCDF
  product.
- Difference from accepted datasets: the catalog has weather stations, radar,
  cloud-mask product bytes, land-cover rasters, lidar classifications, and map
  geometry, but not passive-microwave polar sea-ice concentration fields.
- Numeric representation: the build reads the source NetCDF variable with
  automatic mask/scale conversion disabled and emits the raw uint8 grid codes.

## Materiality

The default bounded plan downloads 96 northern-hemisphere daily grids starting
at 2020-01-01. Each grid is expected to contain about 136,192 byte values
(`448 x 304`), so a complete default run should produce roughly 13.1 million
primary uint8 values before filtering. Verification requires:

- at least 90 primary samples
- at least 10,000,000 primary values
- at least 10 MiB of primary output
- median sample size at least 100,000 values
- nonconstant samples
- primary-output hard cap: 1,000,000,000 bytes

This keeps the collection materially sized while remaining well below the
repository's 1 GB per-dataset cap.

## Script To Run

```bash
bash staging/noaa_cdr_sea_ice_concentration_u8/download.sh
```

After the download succeeds, I will run the local build and verify steps.

## Notes

The build requires Python `netCDF4` and `numpy` so it can read raw variable bytes
without NetCDF scale/mask conversion. If the NOAA/NSIDC archive path changes,
the download script also accepts `SEAICE_URLS_FILE` with exact `source_id<TAB>url`
rows.

## Outcome

Rejected after repeated download failures.

First attempts failed before any NetCDF file was downloaded: the generated URLs
used the flat year-directory form and returned 404 for both tested sensor-token
plans. The staged script was updated to try the NSIDC monthly subdirectory URL
shape first, then the flat fallback, for both `f17` and `f18` candidate tokens.
The candidate should not be retried without an exact upstream URL inventory.
