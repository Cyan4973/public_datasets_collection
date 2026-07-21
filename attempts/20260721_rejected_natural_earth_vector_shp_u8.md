# natural_earth_vector_shp_u8

- Date: 2026-07-21
- Status: rejected
- Candidate dataset: Natural Earth 10m vector Shapefile geometry bytes as `uint8`.
- Source: https://www.naturalearthdata.com/
- Why it looked promising: Natural Earth provides coherent public-domain cartographic vector geometry with substantial polygon and polyline coordinate content.
- Failure class: opaque_container_bytes
- What happened: The accepted recipe copied whole `.shp` files unchanged into `.bin` samples and labeled the Shapefile serialization bytes as a native `uint8` numeric series.
- Evidence: The manifest described "Source ESRI Shapefile geometry bytes" and `conversion = "Copy each source .shp file unchanged into one raw .bin sample."` Local realized output had 12 samples and 96,390,016 primary bytes, but those bytes included Shapefile headers, record headers, part tables, and serialized float64 coordinate fields rather than decoded 8-bit measurements.
- Decision: Remove `natural_earth_vector_shp_u8` from `datasets/` and reject the byte-container recipe. A `uint8` primary series must be an actual 8-bit numeric or symbolic field, not arbitrary Shapefile container bytes.
- Replacement: `natural_earth_10m_geometry_xy_f64` decodes the Shapefile records and emits real float64 longitude/latitude coordinate arrays, one sufficiently large feature geometry per sample.
- Retry conditions: Do not retry this dataset ID as Shapefile bytes. Use the decoded float64 successor, or another documented decoder that extracts typed geometry fields while keeping container metadata auxiliary only.
