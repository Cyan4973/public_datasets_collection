# usgs_3dep_id_northforkpayette_laz_return_number_u8

This recipe collects per-point **LAS 1.4 return numbers** (uint8) from 20 complete LAZ tiles of the USGS 3DEP
work unit `ID_NorthForkPayette_1_2020` (project `ID_NorthForkPayette_2020_B20`). The data is Quality
Level 1 linear-mode lidar flown by Quantum Spatial with a **Riegl VQ-1560i** between 2020-09-03 and 2020-10-09
over the Payette National Forest, Idaho. Each sample holds the return number of every point in one tile,
in file point order.

## What the quantity is, and why it is not a proxy

A discrete-return lidar emits laser pulses. The receiver digitises each pulse's backscatter waveform
and records one point for every echo it detects: canopy top, branches, understory, ground. LAS stores
two 4-bit fields per point in record byte 14 of PDRF 6:

- **return number** (bits 0-3): the echo's ordinal within its pulse. 1 is the first (highest) echo,
  then 2, 3, and so on;
- **number of returns** (bits 4-7): how many echoes that pulse produced.

The return number comes from the sensor's own range-gated echo detection, and it is a measurement of
the vertical structure the pulse passed through. It has a real ordering and magnitude: return 4 lies
physically behind returns 1-3 along the same beam, and the fraction of returns >= 2 is the standard
canopy-penetration and gap-fraction statistic in forestry lidar. It is not an ID, a flag, a text length
or a calendar decomposition. It is also not a generic count of entities: each value is an ordinal
attached to one physical echo, and the stream has a strong structure. The echoes of a pulse are mostly stored consecutively, so they form ascending runs (measured on the built samples: 74-92% of points with return number r > 1 directly follow an r-1; the rest are interleaved, plausibly between the VQ-1560i's two scanner channels, which was not checked)
`1, 2, 3, ...`, which open ground interrupts with long runs of `1`. In the 20 pinned headers, 66-94% of points
are first returns (79% overall; one open-valley tile has 99.9%), and the maximum return number is 5-9.

The header's 15-entry *extended number of points by return* histogram is an independent record of the
same field written by the producer. The build and verify both require the decoded per-tile histogram
to equal it exactly.

## Source and rights

- LAZ tiles: `https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/ID_NorthForkPayette_2020_B20/ID_NorthForkPayette_1_2020/LAZ/`
  (anonymous HTTPS; the tiles are not on the prd-tnm bucket).
- Work-unit VPC, link list, per-tile FGDC metadata and the USGS work-package report come from the
  public `prd-tnm` S3 bucket (anonymous, not requester-pays).
- License: U.S. Government public domain. The AWS Open Data Registry `usgs-lidar.yaml` says
  "License: US Government Public Domain
  https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map". The
  FGDC metadata gives origin "U.S. Geological Survey", `accconst` "None. ..." (USGS Standard
  Disclaimer), and `useconst` with an accuracy disclaimer plus a request to acknowledge the source.
- Lineage, from the work-package report (`USGS_ID_NorthForkPayette_2020_B20_WP_Report.pdf`): Lidar Base
  Specification 2.1, contractor Quantum Spatial Inc, sensor "Riegl VQ-1560i - Aerial Oscillating
  Mirror", QL1, EPSG 6340 + 5703 (GEOID18). Every LAS header reads system identifier `MERGE`, software
  `LiDAR Suite`, creation 2021 day 278, and carries a `NIIRS10` contractor VLR.

## Selection (homogeneity)

`scripts/nfp_tiles.py select` applies this rule, and `discover.sh` documents it. The rule never
looks at return numbers.

1. Every VPC tile must be listed in `0_file_download_links.txt` (9,761 tiles).
2. Only the Idaho area is used: the tile's `proj:bbox` minimum easting must be >= 500,000 m. The work unit
   also contains a **disjoint 596-tile block (11TLL, near lon -118.5 in northeastern Oregon)** about
   200 km west of the basin. Its headers differ slightly (z offset +0.0 instead of -0.0), so it is
   treated as a separate batch and excluded.
3. Tiles must have the full 750 m footprint, which drops clipped boundary tiles.
4. `pc:count` must be in [8.0 M, 11.0 M). This is the lower quartile of per-tile counts (project
   quartiles are 10.3 M / 14.0 M / 18.1 M); it keeps the pure-Python decode (about 60 k points/s per
   process) at about 200 M points.
5. The 962 qualifying tiles are sorted by tile id, and the 20 at evenly spaced ranks are kept. They
   fall in the 11TNK and 11TNL 100 km squares, in the central and northern parts of the basin.

The result is one sensor, one contractor pipeline, one LAS layout and one quantity. Content varies with
land cover. The 11TNK forest tiles have 66-85% first returns and the northern 11TNL tiles 80-94%; maximum returns are 5-9. Tile `11TNK57829297`
(near lon -116.01, lat 44.52, the open Long Valley / Cascade Reservoir floor) has 99.94% first returns
and a maximum return of 4. That is a genuine open-ground/water record, not fill, so verify allows it:
it requires >= 1,000 non-first returns per tile and no value above 99.99%.

## Pipeline

- `download.sh` fetches and pins the VPC, link list (VPC digest drift is only a warning) and WP report
  (strict sha256), re-derives the selection, and fails if it differs from `sources.tsv`. It runs a
  one-byte liveness GET, then fetches each tile with
  `curl -fL -C - --retry 10 --retry-all-errors --speed-limit 1024 --speed-time 120` into `.part`
  inside an 8-attempt outer loop (no `--max-time`). Before keeping a tile it checks size, ETag, LAS
  header (system id, software, PDRF 6 / 30-byte records, scale/offset, point count, pinned 15-entry
  points-by-return), LASzip VLR (compressor 3, POINT14 v3, chunk 50000), contractor VLR, chunk-table
  pointer and the UTM 11N WKT EVLR. Per-tile sha256 (from the first driver download) is pinned in `sources.tsv` and enforced. Expected
  download size is 1,007,660,019 bytes of tiles plus about 31 MB of metadata.
- `build.sh` decodes with `tools/laz/laszip.py` `iter_chunks` (imported, not copied) and takes
  `records[14::30]` through a low-nibble table. It fails on return number 0, on any histogram mismatch
  with the header, on a point-count mismatch, on a constant tile, or if more than 0.1% of points have
  return number > number of returns. It writes
  `samples/<id>/nfp_2020_return_number_u8/<tile stem>.return_number_u8.bin`, the index, and
  `filtered/<id>/build_stats.json` (per-tile return-number and number-of-returns histograms).
- `verify.sh` re-decodes each tile with `decode_points` (the whole-file path), re-extracts return numbers
  with `struct.iter_unpack`, compares bytes, sha256, min/max and histograms (against the header again),
  and checks index fields, stray files, degeneracy, floors and manifest totals.

Expected output: 20 samples, 196,763,633 uint8 values (= bytes), median 9,834,908 per tile (middle values 9,827,450 and 9,842,366).

## Scope notes / not included

- `number_of_returns` (the high nibble of the same byte) is a separate quantity with no header
  histogram to validate against. It is left out rather than added as an unvalidated second series.
- Classification, scan angle, intensity, coordinates and GPS time are other families and are not emitted.
