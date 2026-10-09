# NOAA NGS 2018 Potomac River / Chesapeake Bay topobathy lidar: per-point Intensity (uint16)

Native LAS `Intensity` (unsigned 16-bit) of every point in 48 complete
500 m x 500 m tiles from one NOAA National Geodetic Survey Coastal Mapping
Program topobathymetric lidar project: Digital Coast ID 8727, Riegl
VQ-880-G, flown by Quantum Spatial (QSI) between February and April 2018 over
the Potomac River mouth and the Chesapeake Bay shoreline. NOAA OCM
redistributes the tiles as COPC LAZ in the public NODD bucket
`noaa-nos-coastal-lidar-pds`. Each sample is one tile's intensity stream as a
raw little-endian uint16 array.

## Source and license

- Bucket prefix: `https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/8727/`
  (anonymous HTTPS, not requester-pays): 5,968 `.copc.laz` tiles, 322.6 GB,
  in `delivery01` (3,899) and `delivery02` (2,069).
- Metadata: `metadata_2018_ngs_topobathy_potomac_river_chesapeake.xml`
  (pinned by size and SHA-256), InPort item 56114.
- License: AWS Open Data Registry entry `noaa-coastal-lidar.yaml`: "NOAA data
  disseminated through NODD are open to the public and can be used as
  desired." NOAA asks for attribution of unaltered data and forbids implying
  endorsement. If you modify the data, you may not present it as original,
  unaltered NOAA data. These arrays are one extracted field. The metadata
  says "Access Constraints: None", and its use constraints are only
  accuracy and liability disclaimers.
- Cite: National Geodetic Survey, [Date of Access]: 2018 NOAA National
  Geodetic Survey Topobathy Lidar: Potomac River, Chesapeake Bay [Data Date
  Range], https://www.fisheries.noaa.gov/inport/item/56114.

## What the values are

The tiles are LAS 1.4, point data record format 7 (36-byte records),
compressed with LASzip compressor 3 (layered, variable COPC chunks).
`Intensity` is the `<H` at record offset 12. Values cover the full 0..65535
range:
- Tiles have 981 to 4,877 distinct values; most have about 2,400 to 2,700.
- The most frequent value differs from tile to tile: 0 in three tiles,
  otherwise between about 1,800 and 53,000, mostly 2,000 to 6,500.
- Per-tile mean intensity ranges from about 3,500 to 18,600.
- 65535 is the saturated reading.

The other fields are not emitted, including RGB, which is all zero in this
project.

**Green and NIR channels are interleaved.** The VQ-880-G records green
bathymetric returns and NIR returns (used for the water-surface model)
simultaneously, according to the metadata lineage. The delivered files keep
both channels in one point stream. NOAA converted the original LAS 1.2 PDRF 3
delivery to PDRF 7, and the scanner-channel bits (byte 15, bits 4-5) are 0
for every probed point. The two channels therefore cannot be separated from
stored fields. This recipe emits them interleaved, in native file order, as
one instrument stream. It does not mix programs: there is one project, one
sensor, one contractor and processing chain, and one acquisition season.

**Point order.** Points are emitted in stored order: COPC octree-node
(chunk) order as written by NOAA OCM, with points inside a node in their
stored order. This is the file's native order, not raw acquisition order.

**Shares of 0 and 65535.** Realized over all 153,398,476 points (full
decode, `build.sh`):
- 65535 (saturation) is 0.0055% of all points. The highest single tile is
  `delivery02/20180318_352000e_4242500n` at 0.087%.
- 0 is 0.115% of all points. In 45 of the 48 tiles it is below 0.1%. Three
  tiles are higher: `delivery01/20180326_344000e_4221500n` at 7.4%,
  `delivery02/20180310_376500e_4231000n` at 1.24%, and
  `delivery02/20180215_366000e_4230000n` at 0.30%.
- No value covers more than 7.4% of any tile. Tiles have 981 to 4,877
  distinct values.

The author's earlier 5-chunk probe had estimated about 10% zeros for the
first of those tiles. Per-tile figures, plus scanner-channel and flight-line
counts, are in `filtered/<id>/ingest_stats.json` and the build log. Both 0
and 65535 are kept as native readings; nothing is filtered.

## Selection

`discover.sh` documents how the tile list was resolved on 2026-10-08:
1. List the prefix with anonymous ListObjectsV2 (12 pages).
2. `scripts/select_tiles.py`: in each delivery, take the tiles of
   10,000,000 to 25,000,000 bytes (813 eligible in delivery01, 388 in
   delivery02). This avoids the ~100 KB edge slivers and bounds the download.
   Sort them by key; the key starts with the flight date. Pick 24 at evenly
   spaced positions, which spreads the picks over the flight dates in
   proportion to their eligible counts. The picks cover 18 of the 19
   delivery/flight-date groups (16 distinct dates); delivery01 20180325 is
   not hit.
3. `scripts/probe_decode.py`: for every selected tile, fetch the header,
   chunk table, and five LASzip chunks (first two, middle, last two) by byte
   range, and decode them with `tools/laz/laszip.py`. This checks the
   LAS 1.4 / PDRF 7 / 36-byte layout and that the chunk table matches the
   header point count. All 48 tiles decoded; no tile was replaced. Other
   NOAA PDRF-7 projects have produced "chunk 0 is corrupt" errors. If a tile
   fails, the procedure is to pass it to `select_tiles.py --exclude` and
   document it here. `build.sh` never skips a tile silently.

The pinned result is `sources.tsv`: delivery, key, size, S3 ETag,
LastModified, URL, and header point count, for 48 tiles totalling
868,443,284 bytes and 153,398,476 points.

## Scripts

- `download.sh`: resumable curl (`-C -`, stall-based abort, retries) of the
  metadata XML and the 48 tiles into `downloads/<id>/tiles/`.
  `scripts/check_payload.py` checks each tile's exact size, S3 ETag (MD5 over
  8 MiB parts), LAS 1.4 / PDRF 7 / 36-byte header, and pinned point count.
  An invalid tile is moved aside and the script fails. SHA-256 of every tile
  is written to `downloads/<id>/download_plan.tsv`.
- `build.sh`: local only, multiprocess (`JOBS`, default min(16, cpus)).
  `scripts/build_intensity.py` decodes every chunk of every tile with the
  repository decoder. It checks the decoded point count, the 15
  points-by-return counts, and X/Y/Z bounds against the header. It fails a
  tile with fewer than 64 distinct values or one value above 50%. It writes
  `samples/<id>/potomac_topobathy_intensity_u16/<delivery>__<tile>.bin`, the
  index `index/<id>/samples.jsonl`, and `filtered/<id>/ingest_stats.json`.
- `verify.sh`: `scripts/verify_intensity.py` re-decodes every tile and
  re-extracts Intensity through a different code path (`struct` per record;
  build uses byte slicing). It byte-compares every sample, and checks index
  fields, sha256/min/max, stray files, floors, the 1 GB cap, and the manifest
  `sample_count` / `total_size_bytes`.

Realized output (build and verify on 2026-10-08): 48 samples, 153,398,476
uint16 values, 306,796,952 bytes, median 3,421,887.5 values per sample.
Samples range from 1.60 M to 4.59 M points.

## Relation to other recipes

`dc_lidar_2015_intensity_u16` is topographic NIR lidar over Washington DC
from uncompressed LAS. Its intensity uses only 0..255 (about 95 distinct
values). This recipe is a bathymetric green+NIR Riegl stream that uses the
full 16 bits. It is a different instrument, environment, and value regime.
No other NOAA project is included here.
