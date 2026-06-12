# GeoNames Country Info

Staged recipe for `geonames_country_info`.

- Source: https://download.geonames.org/export/dump/countryInfo.txt
- Local raw payload: `${DATA_DIR:-.data}/downloads/geonames_country_info/geonames_country_info.txt`
- Promote only after a fresh user-run download and passing `build.sh` plus `verify.sh`.
