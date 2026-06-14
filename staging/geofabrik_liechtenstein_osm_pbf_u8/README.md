# Geofabrik Liechtenstein OSM PBF Primitive Blocks (uint8)

This staging recipe extracts OpenStreetMap `OSMData` primitive blocks from the
Geofabrik Liechtenstein `.osm.pbf` country extract and emits one raw uint8
sample per decompressed PrimitiveBlock payload.

The emitted samples are stable machine-facing protobuf bytes. The build strips
only the outer FileBlock container and zlib wrapper; it does not parse OSM
features into local numeric columns and it does not concatenate blocks.
