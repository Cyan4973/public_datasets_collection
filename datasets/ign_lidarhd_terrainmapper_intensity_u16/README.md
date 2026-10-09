# IGN LiDAR HD block 21LHD2GO (Leica TerrainMapper:90560): per-point return intensity, uint16

Native LAS 1.4 point-format-6 `Intensity` (uint16, record offset 12) of every
point in 12 classified 1 km x 1 km COPC tiles from one acquisition block of
the French national IGN LiDAR HD programme. One raw little-endian uint16 array
per tile, in the file's stored COPC order.

## Source and scope

- Programme: IGN LiDAR HD, classified point clouds ("Nuages de points LiDAR
  HD"), delivery `NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22` on the IGN
  Geoplateforme download service (`data.geopf.fr/telechargement`).
- Block: mission `21LHD2GO`, 50 km x 50 km in south-west France (Lambert-93
  NW-corner km x 436..485, y 6334..6383), 2,500 tiles. Flown 2023-08-09 and
  2023-08-17. All 2,500 WFS records carry `capteur = ["Leica TerrainMapper:90560"]`,
  classification `IGN_AUTO_V5`, edition 2025-09-22, so the block has one
  sensor, one classification process and one delivery.
- Selection (`scripts/select_tiles.py`, deterministic): 12 anchors on an
  interior grid (x 442/454/466/478, y 6342/6358/6374), all at least 6 km from
  the block edges, so there are no edge, partial or coastal tiles. Each anchor
  takes its own tile when it has 15M..32M catalogue points and is at most
  230 MB, otherwise the nearest tile that qualifies. 11 anchors took their own
  tile; the 442/6374 anchor moved to 0441-6373.
- Realized: 12 tiles, 312,419,900 points, 624,839,800 primary bytes
  (median tile about 25.9M points, about 52 MB). Download: 2,071,849,594 bytes.

`sources.tsv` pins each tile's name, URL, byte length, MD5 (from the IGN Atom
download feed), WFS acquisition dates, and LAS header point count. The WFS
`nombre_points` differs from the header by a few thousand points, so the
header value is the one pinned. `discover.sh` regenerates `sources.tsv` from
metadata only (one WFS query, 51 Atom pages, 12 range requests of 375 bytes).

## License

Licence Ouverte / Open Licence 2.0 (Etalab). The data.gouv.fr API record
for `nuages-de-points-lidar-hd` (organization: IGN) has license id `lov2`.
Attribute IGN as the source, with the delivery date.

## Pipeline

- `download.sh` fetches the 12 tiles with resumable curl at no more than
  1 request/s, as the service requires. Each tile must match its pinned size
  and MD5, then `ign_intensity.py check` validates LAS 1.4 / PDRF 6 /
  30-byte records, LASzip compressor 3 with only POINT14 v3, the COPC info
  VLR, the Lambert-93 WKT VLR, the COPC hierarchy EVLR, and the pinned header
  point count. SHA-256 must match the value pinned in `sources.tsv` (taken
  from the first download) and is logged in `download_inventory.tsv`. A
  failing tile is moved aside as `.invalid`.
- `build.sh` decodes each tile with `tools/laz/laszip.py` (unmodified,
  pure stdlib), 12 tiles in parallel. It copies bytes 12..13 of every record
  and checks:
  - the decoded point count, and points-by-return against the header;
  - decoded X/Y/Z inside the header bounds;
  - regime guards: at least 1,000 distinct values, max at least 1,000, and no
    single value above 5 % of a tile. A RIEGL-style 1..16 intensity tile
    would fail these.

  Per-tile stats go to `filtered/<id>/ingest_stats.json`: range, distinct
  values, zero and 65535 fractions, order-0 entropy, class histogram, and
  flight-line ids.
- `verify.sh` decodes every tile again and extracts Intensity through
  `struct.iter_unpack`, a different code path from the build's byte slicing.
  It then byte-compares the samples, checks index fields, sha256 and min/max,
  checks manifest totals, and enforces the floors and the 1 GB cap.

## Realized output

| | value |
|---|---|
| samples (tiles) | 12 |
| points / uint16 values | 312,419,900 (22.8M..29.0M per tile, median 25.8M) |
| primary bytes | 624,839,800 |
| distinct values per tile | 4,331..5,962 |
| 0.1 / 50 / 99.9 percentiles | about 290..335 / 912..1789 / 3261..4388 |
| order-0 entropy per tile | 11.06..11.69 bits |
| zero fraction | 1.15e-6 (360 points, all in tile 0442-6342) |
| 65535 (saturated) fraction | 1.73e-7 (54 points across 6 tiles) |
| largest single-value share per tile | at most 0.12 % |
| classes present | 2 ground 36 %, 5 high vegetation 52 %, 4 medium 7.5 %, 3 low 4 %, 1, 6, 9, 17, 64, 66, 67 rare |
| flight lines per tile | 2-3 point-source ids |

## Caveats

- Point order is COPC octree-node order, the stored order, not acquisition
  time. Points are grouped by spatial node, which changes the local
  statistics compared with scan order.
- All points are kept: every class and every return. Tile 0442-6342 holds
  360 class-66 points ("points virtuels", IGN-added synthetic points) and
  exactly 360 zero intensities; they are almost certainly the same points
  (count match per tile, not checked point by point). They are kept as
  recorded (1.15e-6 of the family). Zero and saturated (65535)
  fractions are reported, not filtered.
- Intensity is unnormalized instrument output from one sensor. Across the two
  flight days the gain and range normalisation are assumed constant (same
  serial, same mission). Mixing other LiDAR HD sensors (RIEGL VQ-780 II-S,
  Leica CityMapper-2) would be a different family.
- Decoding is CPU-bound, at about 60k points/s per process.
