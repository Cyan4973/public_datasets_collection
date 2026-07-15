# noaa_cdr_sea_ice_concentration_u8 2020 f17 URL Template

- Date: 2026-07-14
- Status: rejected URL template
- Candidate dataset: NOAA/NSIDC sea-ice concentration CDR
- Attempted URL pattern: `https://noaadata.apps.nsidc.org/NOAA/G02202_V4/north/daily/YYYY/seaice_conc_daily_nh_YYYYMMDD_f17_v04r00.nc`
- Failure class: bad_url_template

## What Happened

After the 2024 `f18` URL pattern failed, the default plan was changed to a
2020 northern-hemisphere `f17` daily window. The retry still returned HTTP 404
for generated URLs such as:

```text
https://noaadata.apps.nsidc.org/NOAA/G02202_V4/north/daily/2020/seaice_conc_daily_nh_20200101_f17_v04r00.nc
```

No NetCDF files were downloaded.

## Decision

Stop guessing NOAA/NSIDC G02202 file paths. Retry this candidate only with an
exact `SEAICE_URLS_FILE` generated from an authoritative archive listing.
