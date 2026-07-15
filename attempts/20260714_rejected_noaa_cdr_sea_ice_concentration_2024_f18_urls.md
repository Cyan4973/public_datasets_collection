# noaa_cdr_sea_ice_concentration_u8 2024 f18 URL Template

- Date: 2026-07-14
- Status: rejected URL template
- Candidate dataset: NOAA/NSIDC sea-ice concentration CDR
- Attempted URL pattern: `https://noaadata.apps.nsidc.org/NOAA/G02202_V4/north/daily/2024/seaice_conc_daily_nh_YYYYMMDD_f18_v04r00.nc`
- Failure class: bad_url_template

## What Happened

The first default URL plan generated 16 northern-hemisphere daily files for
2024-01-01 through 2024-01-16 using sensor token `f18`. Every generated URL
returned HTTP 404.

The URL plan was corrected to use an older bounded G02202 V4 window with
sensor token `f17`, starting at 2020-01-01, and to derive the year directory
from the generated date.

## Decision

Do not retry the 2024 `f18` default template. Use the updated default URL plan
or provide exact URLs with `SEAICE_URLS_FILE`.
