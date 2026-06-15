# NOAA NEXRAD Level-II Moments Int16

Download-only staging recipe for bounded NOAA NEXRAD Level-II radar archive files from the public AWS Open Data bucket.

The target material is native operational radar moment data. Natural sample boundaries will be one Level-II archive volume file unless later parsing proves a more precise sweep/message boundary is required.

Run:

```bash
staging/noaa_nexrad_level2_moments_i16/download.sh
```

Default scope is `KTLX` on `2024-05-20`, first `${FILE_LIMIT:-8}` volume files discovered from the public bucket listing. Override `STATION`, `DATE_YYYYMMDD`, and `FILE_LIMIT` as needed.
