# usgs_3dep_cameronpeak_vq1560ii_scan_angle_i16

Native LAS 1.4 per-point **scan angle** (signed int16, 0.006° units) from 24
complete LAZ tiles of the USGS 3DEP work unit `CO_CameronPkFire_1_2021`
(project `CO_CameronPeakWildfire_2021_D21`). The data were flown with a Riegl
VQ-1560 II between 2021-09-07 and 2021-09-22 over the 2020 Cameron Peak burn
area in the Colorado Front Range. The recipe emits one little-endian int16
array per tile, holding every point in delivered file order.

## Source and license

- LAZ tiles: `https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/CO_CameronPeakWildfire_2021_D21/CO_CameronPkFire_1_2021/LAZ/`
- VPC, link list, QC report and per-tile FGDC metadata: the public
  `prd-tnm` S3 bucket (anonymous, not requester-pays).
- License: U.S. Government public domain. USGS Copyrights and Credits says:
  "USGS-authored or produced data and information are considered to be in
  the U.S. public domain." In the per-tile FGDC metadata, `origin` is
  "U.S. Geological Survey" and `accconst` is "None."; `useconst` asks for
  acknowledgement and for modifications to be described. The modification
  here is that only the scan-angle field of each record is kept.

## Selection (`scripts/cpk_tiles.py select`, documented by `discover.sh`)

1. Take the VPC features whose URL is in `0_file_download_links.txt`
   (1,167 tiles).
2. Keep only the main delivery batch, VPC `datetime == 2022-03-11T00:00:00Z`
   (1,156 tiles). This drops the 11 re-delivered tiles; 9 of them use the
   variant system id `Riegl VQ-1560II`.
3. Keep only tiles with a full 5,000 ft footprint.
4. Keep tiles with `pc:count` in [6 M, 14 M). The project median is 14.2 M,
   so this bound limits pure-Python decode time and primary size.
5. Sort the tiles by id and take 24 at evenly spaced ranks of the 380 that
   qualify. The picks range from w2995 to w3155 and from n1355 to n1550.

The rule never looks at scan angles. `download.sh` re-derives the selection
from the live VPC and link list and stops if it differs from `sources.tsv`.

## Pipeline

- `download.sh` fetches the VPC, link list and LazQC LPC report from S3.
  It then fetches the 24 pinned tiles from rockyweb, 4 at a time, using
  `curl -C -` with stall detection and outer retries. A single stream runs at
  about 0.5 MB/s. Each tile is checked against its pinned size and ETag and
  its full LAS 1.4 header, VLR and chunk-table signature:
  - system id `Riegl VQ-1560 II`, software `GeoCue LAS Updater`
  - compressed PDRF 6, 30-byte records, scale 0.001
  - point count equal to VPC `pc:count`, plus the pinned points-by-return
    counts
  - LASzip compressor 3 POINT14 v3
  - Colorado North (ftUS) WKT
  - sha256, once pinned

  Total: 1,985,279,750 bytes.
- `build.sh` decodes every tile with `tools/laz/laszip.py iter_chunks` and
  keeps record bytes 18-19 unchanged. It checks the decoded per-return
  histogram against the header (decode integrity), the LAS 1.4 limit of
  ±30,000, and non-degeneracy (at least 100 distinct values, top value at
  most 50%). It writes
  `samples/<id>/cpk_2021_scan_angle_i16/<tile stem>.scan_angle_i16.bin` and
  the index.
- `verify.sh` re-decodes each tile with `laszip.decode_points`, a different
  path through the decoder. It re-extracts the angles with
  `struct.iter_unpack` and compares bytes, hashes, min/max, distinct counts,
  the index and manifest totals. It also requires a per-tile span of at
  least 2,000 units and a family range of at least ±3,000 (±18°). Both signs
  are not required per tile, because some tiles see only one side of the
  swath.

Expected output: 24 samples, 245,581,947 values, 491,163,894 bytes. The
median sample has 10.8 M values (range 6.06 M to 13.6 M).

## Caveats

- **Effective resolution.** In a probed 200,000-point excerpt of tile
  w3000n1480 (decoded from range GETs), the values fall on a lattice of about
  16 units (≈0.096°), not on every 0.006° step. A full ±35° swath therefore
  has roughly 700 levels: more than 8 bits need, but not the full int16
  resolution. This is how the field was delivered; the recipe does not
  transform it.
- **Point order.** Points are kept in file order. GPS time is not monotonic
  within a chunk, so the contractor's delivery is not pure acquisition order.
  Within short runs, the angle ramps along scan lines.
- **Withheld points.** Class 7 and 18 noise points are flagged withheld and
  are kept, like every other record.
- **Nearest families.** `srsp_scotland_phase1_lidar_scan_angle_i8` is the
  same LAS concept at 8 bits: whole-degree Scan Angle Rank from PDRF 1, with
  a different sensor and country. Other rockyweb recipes collect different
  projects and fields (North Fork Payette return number u8, NC Geiger X
  i32).
