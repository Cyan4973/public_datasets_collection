`geonames_cities5000` emits native numeric geospatial fields from the public GeoNames `cities5000` archive.

Series:
- `geonames_latitude`
- `geonames_longitude`
- `geonames_population`

Missing-value policy:
- blank numeric fields are filtered independently per series
- malformed rows are fatal
