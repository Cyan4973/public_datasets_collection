# Natural Earth 10m Geometry XY Float64

This recipe downloads selected Natural Earth public-domain 10m vector layers,
parses their ESRI Shapefile `.shp` geometry records, and emits decoded
longitude/latitude coordinate streams as little-endian `float64`.

The primary sample boundary is one Shapefile feature record. The build keeps
only polygon and polyline feature records with at least 1,000 coordinate values
(`x0, y0, x1, y1, ...`). Point records and smaller geometries are below the
repository's natural-record floor and are not concatenated.
