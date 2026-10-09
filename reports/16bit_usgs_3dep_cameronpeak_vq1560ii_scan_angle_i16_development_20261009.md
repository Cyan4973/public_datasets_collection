# USGS 3DEP Cameron Peak LAS 1.4 scan angle int16 development

## Outcome

Accepted `usgs_3dep_cameronpeak_vq1560ii_scan_angle_i16`. It is the first 16-bit corpus family to carry the per-point LAS 1.4 **scan angle**: the angle of the outgoing pulse from nadir, in 0.006° units. The values come from complete USGS 3DEP LAZ tiles of work unit `CO_CameronPkFire_1_2021`, flown with a Riegl VQ-1560 II on 2021-09-07..22 over the 2020 Cameron Peak burn area in Colorado.

Novelty is new content in a known modality, not a new quantity. The same LAS concept is already accepted at 8 bits as `srsp_scotland_phase1_lidar_scan_angle_i8` (LiDAR for Scotland, Blom 2011-12, PDRF 1 whole-degree Scan Angle Rank). This recipe differs in source, sensor, width and resolution: 0.006° units on a delivered ~0.096° lattice, 661 levels, against 59 whole-degree levels. Existing 16-bit lidar families, local and downstream, carry intensity only.

The zlsim breadth verdict is OK, not redundant:
- The nearest family is downstream `power_global_intensity` at distance 0.0831, with loss 0.0.
- Next come `tum_rgbd_depth_u16` at 0.113 (loss −0.040) and `air_co` at 0.120 (loss −0.016).
- Several existing compressors match the candidate's own (ratio 11.88), but no family is within the 0.05 feature-distance threshold, and no lidar family is among the 10 nearest.

## Source and rights

- LAZ tiles: `https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/CO_CameronPeakWildfire_2021_D21/CO_CameronPkFire_1_2021/LAZ/` (anonymous HTTPS).
- The work-unit VPC (1,167 STAC features), `0_file_download_links.txt`, the per-tile FGDC metadata and the USGS LazQC 2.0 LPC report come from the public, non-requester-pays `prd-tnm` S3 bucket. The report is pinned by sha256 `22c8523e…`.
- Lineage, from the QC report:
  - LAS 1.4 PDRF 6 in all 1,167 tiles; generating software 'GeoCue LAS Updater'.
  - System id 'Riegl VQ-1560 II' in 1,158 tiles and 'Riegl VQ-1560II' in 9.
  - Scan-angle rank −33..35°.
- License: US Government Public Domain.
  - USGS Copyrights and Credits: "USGS-authored or produced data and information are considered to be in the U.S. Public Domain."
  - The per-tile FGDC XML (w3060n1355) gives origin "U.S. Geological Survey" and accconst "None.".
  - Its useconst is an accuracy disclaimer plus requests to acknowledge the originating agencies, describe modifications, and not misrepresent the data. The manifest records the modification: only the scan-angle field is kept.

## Shape and conversion

- **Natural record:** one complete published 5,000 ft LAZ tile. A sample is the scan angle of every point in that tile, in delivered file point order. Nothing is re-sorted or dropped, and withheld class 7/18 noise points are kept.
- **Selection rule** (`scripts/cpk_tiles.py select`). It never looks at scan angles, and `download.sh` re-derives it from the live VPC and link list and fails if the result differs.
  1. Main delivery batch only (VPC datetime 2022-03-11). This drops 11 re-delivered tiles, 9 of them with the variant system id.
  2. Full 5,000 ft footprint.
  3. `pc:count` in [6 M, 14 M); the project median is 14.2 M.
  4. Of the 380 qualifying tiles, keep the 24 at evenly spaced ranks by tile id, from w2995 to w3155 and n1355 to n1550.
- **Download validation:** for every tile, pinned size, ETag and sha256; full LAS 1.4 header (system id, software, creation day, PDRF 6 with 30-byte records, scale 0.001, WKT bit, no EVLRs, point count equal to VPC pc:count, pinned 15-entry points-by-return); LASzip VLR (compressor 3, POINT14 v3, chunk 50,000); contractor VLR; Colorado North (ftUS) WKT VLR; and the chunk-table signature.
- **Decode:** `tools/laz/laszip.py` `iter_chunks`. The build keeps record bytes 18-19 unchanged as little-endian int16. Coordinates, intensity, return and flag bytes, classification, point source id and GPS time are not emitted.
- **Integrity and missing values:** the LAS scan angle has no missing sentinel, and 0 is nadir. The decoded per-return histogram must equal the header counts, and values must lie within the LAS limit of ±30,000. Build and verify both also require at least 100 distinct values and no value above 50% of a tile. Verify additionally requires a per-tile span of at least 2,000 units and a family range of at least ±3,000.
- **Effective resolution:** every tile's values sit 100% on 16k±1, with gaps of 15, 16 or 17. This looks like truncation of an upstream 0.096° step (360°/3750) converted to 0.006° units. It is the field as delivered, not a recipe transform, and it is identical across all tiles.

## Accepted output

| Item | Value |
|---|---|
| Tiles validated and decoded | 24 of 380 qualifying (1,167 in the work unit) |
| Primary samples | 24 |
| Primary values | 245,581,947 |
| Primary bytes | 491,163,894 |
| Minimum sample | 6,060,150 values (w3095n1375) |
| Median sample | 10,693,543.5 values (mean of the 12th and 13th; the manifest quotes the upper one, 10,820,823) |
| Maximum sample | 13,616,373 values (w2995n1480) |
| Pinned LAZ bytes | 1,985,279,750 (1,989,453,723 including metadata) |
| Family range | −5103..5456 (about −30.6..32.7°) |
| Distinct values | 272–637 per tile; 661 across the family |
| Top-value share | at most 0.49% per tile; 0.197% for the family (value 4320) |
| Zero share | 0.17% |
| Negative share | 46.6% |
| H0 per tile | 8.0–9.2 bits |
| Delta entropy per tile | 1.41–1.68 bits |
| Zero-delta share per tile | 0.70–0.76 |
| zlsim own ratio / verdict | 11.88 / OK (nearest distance 0.0831) |

Seven tiles see only one side of the swath (for example w3140n1375 at 576..4912 and w3095n1375 at −4896..335). They are genuine natural records chosen by the selection rule, which never looks at scan angles.

## Judge checks

- **Gate:** `gate.py` gives PASS with no warnings.
- **Verify:** I re-ran `verify.sh`; it exited 0 in 3:27. All 24 tiles were re-decoded through the whole-file `decode_points` path with `struct.iter_unpack` extraction and matched the samples byte for byte. The return histograms, index fields and manifest totals were re-checked.
- **Build:** `build.sh` uses only local files; its only URLs are string constants used for selection checks. All 24 sha256 values are pinned in `sources.tsv`, and my own sha256 of w3060n1355 and w3140n1375 matches the pins.
- **Independent field check:** using only laszip's chunk-table reader, I read the raw 30-byte first point at the start of every LAZ chunk directly from the file. Its bytes 18-19 equal `sample[50000*i]` for all 809 chunks of w2995n1480, w3095n1375, w3140n1375 and w3055n1435. This confirms the field offset and alignment without the arithmetic decoder.
- **Bytes** (all 24 samples, stdlib Python):
  - Lattice share 1.0 in every tile.
  - Entropy and run statistics as tabled above.
  - 24 distinct sample hashes and no duplicate 64 KiB blocks within any tile.
  - 50k-chunk means sweep across the swath, and fine-scale ramps follow scan lines: natural per-tile records, not concatenations.
- **Rights:** I opened the USGS Copyrights and Credits page and the per-tile FGDC XML myself. No credentials appear in any script, and the data contain no personal information.
- **Novelty:** `novelty.py` was run with the URLs and terms, `--vocabulary`, and the type/instrument/archive keys.
  - Laser_range has 19 families, but none at 16 bits carries scan angle; downstream 16-bit lidar is `dc_lidar_intensity_u16` only.
  - Same instrument line: 0. Same archive collection: 0.
  - The project is not used by any other recipe.
- **Residual caveats, not blocking:**
  - The quantity is smooth and compresses heavily (about 12×). Existing smooth 16-bit compressors handle it about as well as its own, but its feature distance is above the redundancy threshold.
  - The pc:count bound keeps the lower half of tiles by point count.
  - About 25% of downloaded bytes are kept, which is acceptable because LAZ cannot be projected server-side.
