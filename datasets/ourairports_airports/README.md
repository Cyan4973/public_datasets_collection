`ourairports_airports` emits native numeric airport fields from the public OurAirports airport CSV.

Series:
- `ourairports_latitude`
- `ourairports_longitude`
- `ourairports_elevation_ft`

Missing-value policy:
- blank `elevation_ft` values are filtered
- malformed rows are fatal
