# NOAA CO-OPS Stations

Staged recipe for `noaa_coops_stations`.

- Source: https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json
- Local raw payload: `${DATA_DIR:-.data}/downloads/noaa_coops_stations/noaa_coops_stations.json`
- Promote only after a fresh user-run download and passing `build.sh` plus `verify.sh`.
