# Protomaps OpenStreetMap Basemap (PMTiles v3): Zoom-15 Vector-Tile Building-Footprint Vertex Coordinates (MVT 4096-Extent Tile Space) Int16

- Candidate id: `protomaps_osm_z15_building_coords_i16`
- Width: int16
- Quantity: Building polygon vertex coordinates (x,y) in Mapbox Vector Tile integer tile space (extent 4096, buffer to -64..4160), decoded from the MVT zigzag-delta command stream of the 'buildings' layer at zoom 15.
- Source: https://docs.protomaps.com/basemaps/downloads
- Resources: https://build.protomaps.com/20250120.pmtiles, https://build-metadata.protomaps.dev/builds.json, https://github.com/protomaps/basemaps
- License: ODbL 1.0 (OpenStreetMap Produced Work); Natural Earth parts public domain
- License evidence: https://github.com/protomaps/basemaps/blob/main/README.md
- License quote: Tilesets are ODbL, attribute OSM ... The tilesets that power the Protomaps basemap are Produced Works of the OpenStreetMap dataset under the Open Database License.
- Natural record: One z15 vector tile's buildings layer: all building ring vertices as interleaved int16 (x,y) in feature/ring order. A dense urban tile has about 12k vertices, i.e. 24k values.
- Estimated samples: 1,500
- Estimated primary values: 30,000,000
- Estimated download bytes: 200,000,000
- Estimated primary bytes: 60,000,000
- Decode path: curl range GETs only, never the 129 GB archive. Read the 127-byte PMTiles v3 header, then the root directory (gzip, about 15 KB). For each target z15 tile (a deterministic list of city-centre tile blocks), compute the Hilbert tile id, range-GET the needed leaf directory (about 100 KB gzip, varint-encoded) and then the tile (gzip MVT, about 100-170 KB). In Python, gzip plus a minimal protobuf varint parser decodes the layer 'buildings' and the geometry command stream (MoveTo/LineTo/ClosePath with zigzag deltas) into absolute tile coordinates, emitted as int16 LE. A working stdlib prototype of exactly this path was run during scouting.
- Novelty kind: new_source
- Measurement type: gis_vector_geometry
- Instrument line: openstreetmap_protomaps_mvt
- Archive collection: build.protomaps.com
- Novelty evidence: novelty.py --url build.protomaps.com --terms protomaps pmtiles 'vector tile': no matches. gis_vector_geometry exists only at 32/64 bits (Google Open Buildings f32 lat/lon, Natural Earth f64). There is no quantized tile-space vector geometry at 16. The nearest 16-bit coordinate families are font glyph outlines (google_fonts_glyf i16, downstream truetype glyph coords), which are curve control points in em space, not rectilinear building rings on a 4096 grid.
- Homogeneity: One layer (buildings), one zoom (15), one extent (4096) and one build (pinned 20250120, v4). Other layers (pois, roads, landuse, earth) have different geometry types and coordinate ranges and are excluded. Tiles are chosen as urban blocks so records are well above the 1000-value median floor. Skip tiles with fewer than about 1000 building values rather than padding.
- Risks: (1) Possible compression similarity to the glyph-coordinate families; the zlsim gate decides. (2) Build retention: older builds persist (20230918 still returns 200; 62 retained builds listed), but a dated build could be pruned. Pin the size from builds.json and fail loudly. (3) The ODbL share-alike/attribution notice must be recorded (ODbL is already accepted in several recipes). (4) Coordinates are decoded from the delta command stream. This is the documented MVT geometry semantics, analogous to the accepted glyf decoding, but the manifest should state it.
- Probe evidence: The builds.json listing works (latest 20261008, 138.7 GB). The 20250120 header is PMTiles v3, internal/tile compression gzip, tile type MVT, zoom 0-15, and its root directory decoded to 2917 leaf-dir entries. The prototype decoded z15 tile 9649/12314 (Times Square): 113 KB gzip, buildings 1686 features / 11,840 vertices, range -64..4160, extent 4096. z15 Paris tile 16598/11273: buildings 12,387 vertices, same range. HEAD of 20230918.pmtiles returned 200 (old builds retained).

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_163746.jsonl`).
