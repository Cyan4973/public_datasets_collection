# noaa_coastal_maine_topobathy_classification_u8

Per-point LAS classification codes (uint8) from the NOAA NGS 2022-23 Coastal
Maine topobathymetric lidar project (Digital Coast / DAV ID 10423, InPort
77189). NV5 acquired it with Leica Chiroptera HawkEye 4X sensors, which carry a
green bathymetric laser and an NIR topographic laser. NOAA publishes it as
44,316 COPC tiles (LAS 1.4, point data record format 6, 500 m x 500 m) in the
public NODD bucket `noaa-nos-coastal-lidar-pds`.

Each sample is the full classification array of one tile: byte 16 of every
30-byte PDRF-6 record, copied unchanged, in stored COPC order. That order
follows the octree-node chunks, not acquisition order. One field only.

## Source and license

- Tiles: `https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/10423/<block>/<date>_<E>e_<N>n.copc.laz`
- Metadata: `metadata_2022_ngs_coastalMaine.xml`. It covers sensor lineage,
  PDRF 6, the contractor and final classification schemes, and
  "Access Constraints: None".
- License: the AWS Open Data Registry entry for the bucket says "NOAA data
  disseminated through NODD are open to the public and can be used as
  desired". NOAA asks for attribution and forbids claiming endorsement, or
  presenting modified data as unaltered NOAA data. It is a US Government work.
  Cite: National Geodetic Survey, 2022-2023 NOAA NGS Topobathy Lidar: Coastal
  Maine, https://www.fisheries.noaa.gov/inport/item/77189.
- The metadata includes a generic notice ("compiled dynamically ... removed 10
  days after 2025-09-12"). Despite that, the objects were live on 2026-10-08:
  the listing worked, range GETs returned 206, and the headers parsed.

## Selection rule (declared before decoding, independent of class content)

`scripts/select_tiles.py` works only from NOAA's published listing and its
per-tile `minmax_2022_ngs_coastalMaine_m10423.csv` (XYZ extents, NAVD88
GEOID18 heights). `discover.sh` reproduces `sources.tsv` from them.

1. Full footprint: x and y extents of at least 499 m. This drops clipped
   project-edge tiles.
2. Shoreline-straddling: published `min_z <= -3.0 m` and `max_z >= +3.0 m`,
   i.e. the tile spans the intertidal zone. 8,711 of 44,316 tiles qualify,
   between 555 and 1,363 per block.
3. In each of the 10 blocks, sort the qualifying keys and take the 5 tiles at
   ranks `floor((2i+1)·m/10)`, i = 0..4.

Result: 50 tiles, 2,076,786,177 bytes to download, and 312,002,256 points
according to the headers, which is the primary output in bytes. Tile sizes
range from 28 to 58 MB.

Caveat: the z-extent includes noise points, so a tile can qualify partly
because of outliers. The rule only guarantees that the tiles are coastal; it
does not guarantee any particular class mix. Content-based selection was
deliberately avoided.

## Pipeline

- `download.sh` fetches the metadata XML (pinned SHA-256) and the 50 tiles
  with resumable curl. `scripts/check_payload.py` then checks each tile's exact
  size, its S3 multipart ETag (recomputed as the MD5 of the MD5s of its 8 MiB
  parts), a LAS 1.4 header with PDRF 6 (compressed) and 30-byte records, and
  the pinned point count. The SHA-256 of each tile goes into
  `downloads/<id>/download_plan.tsv`. Since the first driver download
  (2026-10-08), it is also pinned in `sources.tsv` column 11, and
  `download.sh` enforces it.
- `build.sh` uses local files only. It decodes every LASzip chunk with
  `tools/laz/laszip.py` (compressor 3, POINT14 v3, variable COPC chunks), using
  parallel worker processes (`JOBS` overrides the count), and emits
  `records[16::30]`. Integrity checks per tile:
  - the decoded count matches the header;
  - all 15 extended points-by-return counts match the header;
  - XYZ falls inside the header bounds;
  - every layer decoder consumes exactly its layer bytes.

  Constant tiles are fatal, and so are tiles with more than 1% of codes
  outside the documented scheme. The per-tile and family class histograms,
  scanner-channel counts and classification-flag counts go to
  `filtered/<id>/ingest_stats.json`.
- `verify.sh` re-decodes each tile through the separate whole-file path
  (`decode_points`) and requires byte equality with the sample. It also checks
  SHA-256, min/max, histogram, the index fields and the manifest totals. It
  rejects constant samples and samples where one code covers more than 99.9%
  of points, and requires at least half of the tiles to carry both code 40
  and code 41 or 42.

Missing values: none. Every point is emitted, including withheld, overlap and
synthetic points, each with its own code.

## Realized output (build 2026-10-08)

- 50 samples, 312,002,256 bytes. Points per tile: median 6.17 M, range
  4.50 M to 8.90 M.
- Download: 2,076,786,177 bytes. Build takes about 4.7 min and verify about
  4 min with 25 worker processes.
- Family class histogram:

  | Code | Class | Points | Share |
  |---|---|---|---|
  | 1 | unclassified | 104,038,149 | 33.35% |
  | 2 | ground | 35,031,095 | 11.23% |
  | 40 | bathymetric bottom | 14,110,674 | 4.52% |
  | 41 | water surface | 6,451,260 | 2.07% |
  | 42 | derived water surface | 95,877,645 | 30.73% |
  | 45 | water column | 56,316,188 | 18.05% |
  | 64 | submerged vegetation | 177,245 | 0.06% |

- 46 of 50 tiles carry both 40 and 41/42. The other 4 contain only
  1/41/42/45: water surface and column with no detected bottom.
- The most common code in a tile covers between 29.9% and 92.3% of its
  points. The 92.3% case is class 1 in
  `block04_01/20230801_464500e_4870000n`.
- Scanner channels: 0 has 75.2 M points, 1 has 95.9 M (all of class 42), 2 has
  1.9 M and 3 has 139.1 M. Points-by-return and XYZ-bounds cross-checks pass
  on every tile. That also exercises the decoder's channel-switch paths, which
  `tools/laz/README.md` lists as unverified.

## Probe evidence (2026-10-08)

- Listing: 44,326 keys (44,316 `.copc.laz`); `minmax` CSV with 44,316 rows,
  all matched.
- The 4 KiB header prefixes of all 50 selected tiles parse as LAS 1.4 with
  point format byte 134 (6 plus the compression bit) and 30-byte records.
- Decoding 25 chunks spread across
  `block02_03/20221123_523500e_4891500n.copc.laz` (246,343 points) from range
  GETs gave classes {1: 182,327, 2: 51,419, 40: 1,665, 41: 50, 42: 9,321,
  45: 1,561}, on scanner channels 0-3. Every chunk passed the decoder's
  layer-consumption check. Channel 1 points correspond one-to-one with class
  42 (synthetic water surface). The COPC root chunk alone held only classes
  1/2, so class composition is not uniform across the octree order.

## Caveats for review

- Classification is a categorical code with ordering meaning only within the
  ASPRS table. The corpus already accepts this kind of payload
  (`dc_lidar_2015_classification_u8`, `sentinel2_l2a_scene_classification_u8`).
  The nearest family is DC 2015 urban topographic lidar classes (1-17, flight
  order). This one is a topobathy code regime (40/41/42/45/64 plus 1/2) from a
  green-laser sensor in COPC octree order. Whether the bytes differ enough is
  for `zlsim.py gate` to decide.
- Class 42 (derived/synthetic water surface) makes up 30.7% of points. These
  are contractor-generated points: every one has the synthetic flag set and
  sits on scanner channel 1. They are still a published, delivered point
  class of the files, but they are not laser returns.
- No noise codes (7/18) or 43/65 points occur in the 50 tiles. The delivered
  files appear to omit or remove noise.
- The scanner-channel context-switch path of the POINT14 v3 decoder is marked
  unverified in `tools/laz/README.md`, and this data uses channels 0-3. The
  probe chunks passed the exact layer-consumption checks, and the build also
  cross-checks points-by-return and XYZ bounds against every header.
