# Protomaps OSM Basemap Z15 Building Vertex Coordinates (int16)

Building footprint vertices from zoom-15 Mapbox Vector Tiles of the Protomaps
planet basemap. The source is the dated build `20250120.pmtiles`
(129,605,595,792 bytes, basemap v4.0.4, OSM replication 2025-01-20T04:00Z).
Each sample is one z15 tile's `buildings` layer: every polygon ring vertex as
interleaved `x, y` little-endian int16 in MVT tile space. The extent is 4096
and the 64-unit buffer gives a range of -64..4160.

## Source and license

- Builds: <https://build-metadata.protomaps.dev/builds.json>. The archive is
  served from <https://build.protomaps.com/20250120.pmtiles>.
- License: ODbL 1.0, as an OpenStreetMap Produced Work. The
  protomaps/basemaps README says "Tilesets are ODbL, attribute OSM". The
  docs download page says the archive is "distributed as an Open Database
  License Produced Work (OpenStreetMap attribution required)".
  Attribution: **© OpenStreetMap contributors**.

## Selection

`cities.tsv` lists 74 city centres across six continents. For each centre,
the block is the 8x8 z15 tile square whose origin is aligned to multiples of
8 and whose centre is nearest the city centre. An aligned square is one
contiguous Hilbert tile-id range. The archive is clustered, so each block's
tile payloads sit in one contiguous byte span.

`discover.sh` resolved the spans and leaf directories from the root
directory. The results are pinned in `blocks.tsv` and `leaves.tsv`. There are
4,645 tiles in span; 91 tiles whose payload was deduplicated outside the span
are skipped. Tiles without a buildings layer, or with fewer than 1,000
building values, are also skipped. One tile is one sample, and tiles are never
merged.

## Pipeline

- `download.sh` fetches only pinned byte ranges, about 214 MB in total:
  - the header and root region
  - the metadata
  - 72 leaf directories
  - 74 block spans

  It checks the archive size and ETag. It checks pinned SHA-256 sums for the
  header, metadata and leaves. Each span gets a size check and a gzip/MVT
  parse of every tile. The full 129.6 GB archive is never fetched.
- `build.sh` resolves each tile through the root and leaf directories and
  gunzips the MVT. It decodes the `buildings` polygon command streams
  (MoveTo/LineTo/ClosePath with zigzag deltas; the cursor resets per feature;
  ClosePath adds no vertex) and writes one int16 sample per tile.
- `verify.sh` re-decodes every tile and compares the bytes. It also checks the
  index fields, the range, non-degeneracy, duplicates, the floors and the
  manifest totals.
- `scripts/pmtiles_mvt.py` is a pure-stdlib PMTiles v3 and MVT decoder with a
  synthetic self-test: the Hilbert spec vectors, a directory round trip, and
  polygon decoding with holes, negative values, and the per-feature cursor
  reset.

## Realized output

| Item | Value |
| --- | --- |
| Samples | 3,700, one per tile, from all 74 blocks |
| Values | 50,182,766 int16 (100,365,532 bytes) |
| Values per tile | median 8,502; p10 1,884; p90 30,710; max 129,306 |
| Tiles skipped | 651 below 1,000 values, 294 without a buildings layer, 91 deduplicated outside the span |
| Samples per continent | Europe 1,272, Asia 846, North America 645, Africa 466, South America 280, Oceania 191 |

Coordinates span exactly -64..4160. No non-polygon features occur in the
buildings layer at z15.
