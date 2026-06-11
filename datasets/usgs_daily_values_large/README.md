# USGS Daily Values Large

Staged recipe for `usgs_daily_values_large`.

- Source: https://waterservices.usgs.gov/
- Local raw payload: `${DATA_DIR:-.data}/downloads/usgs_daily_values_large/usgs_daily_values_large.json`
- Promote only after a fresh user-run download and passing `build.sh` plus `verify.sh`.
