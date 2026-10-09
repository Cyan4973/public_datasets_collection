# USGS 3DEP North Fork Payette LAS return number uint8 development

## Outcome

Accepted `usgs_3dep_id_northforkpayette_laz_return_number_u8`, the first corpus family to carry the LAS per-point **return number**: the ordinal position (1, 2, 3, …) of each recorded echo within its laser pulse. The values come from complete USGS 3DEP QL1 LAZ tiles of work unit `ID_NorthForkPayette_1_2020`.

Existing 8-bit airborne-lidar families carry classification (DC 2015, Coastal Maine topobathy), scan angle rank (LiDAR for Scotland) and automotive intensity (Boreas). None carries return number. This is a new quantity in a known modality, not a new modality. The zlsim breadth verdict is OK: the nearest families are downstream `cms_LHE_Njets` and `gas_label`, both at distance 0.0578. Their losses are negative (−0.19 and −0.026), so they are not compression-equivalent.

## Source and rights

- LAZ tiles: `https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/ID_NorthForkPayette_2020_B20/ID_NorthForkPayette_1_2020/LAZ/` (anonymous HTTPS).
- Work-unit VPC, link list, per-tile FGDC metadata and the work-package report all come from the public, non-requester-pays `prd-tnm` S3 bucket.
- Sensor lineage, from the work-package report (sha256 `ba001930…`): Quantum Spatial, Riegl VQ-1560i, Lidar Base Specification 2.1, QL1, collected 2020-09-03..2020-10-09.
- License: US Government Public Domain.
  - The AWS Open Data Registry `usgs-lidar.yaml` says: "License: US Government Public Domain https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map".
  - The per-tile FGDC metadata gives origin and publisher "U.S. Geological Survey" and accconst "None", plus the standard disclaimer.
  - Its useconst is an accuracy disclaimer and a request for acknowledgement and for a description of modifications. The manifest records both.

## Shape and conversion

- **Natural record:** one complete published 750 m LAZ tile. A sample is the return number of every point in that tile, in the delivered file point order.
- **Selection rule.** It never looks at return numbers; `download.sh` re-derives it from the live VPC and fails if the result differs.
  1. Idaho area only: minimum easting ≥ 500,000 m. This drops the disjoint 596-tile Oregon 11TLL block, whose header differs.
  2. Full 750 m footprint.
  3. `pc:count` in [8 M, 11 M), the lower quartile.
  4. Of the 962 qualifying tiles, keep the 20 at evenly spaced ranks by tile id.
- **Coverage:** the 20 tiles fall in the 11TNK and 11TNL 100 km squares. The README states this.
- **Decode:** `tools/laz/laszip.py` `iter_chunks` (LASzip compressor 3, POINT14 v3, 50,000-point chunks). The build keeps the low nibble of record byte 14 (`b & 0x0F`) unchanged. Number of returns, classification, scan angle, intensity and coordinates are not emitted.
- **Missing values:** LAS return numbers have no missing sentinel, and 0 is invalid and fatal. The decoded per-tile histogram must equal the header's 15-entry extended points-by-return counts exactly, in both build and verify.

## Accepted output

| Item | Value |
|---|---|
| Tiles validated and decoded | 20 of 962 qualifying (9,761 in the work unit) |
| Primary samples | 20 |
| Primary values | 196,763,633 |
| Primary bytes | 196,763,633 |
| Minimum sample | 8,321,172 values |
| Median sample | 9,834,908 values |
| Maximum sample | 10,980,768 values |
| Pinned LAZ bytes | 1,007,660,019 (1,039,066,311 including metadata) |
| Return number 1 | 0.7917 |
| Return number 2 | 0.1617 |
| Return number 3 | 0.0395 |
| Return number 4 | 0.0064 |
| Return number 5 | 0.00065 |
| Return number 6 | 4.6e-5 |
| Return numbers 7–9 | rare |

Fill warning: the dominant value is return 1 (first returns), a genuine measurement and not fill. zlsim's mode_share of 0.916 is the maximum over six sampled windows. Per-tile first-return shares run from 0.66 to 0.94, plus one near-constant tile, 11TNK57829297 (Long Valley / Cascade Reservoir floor, 0.9994). That tile is retained as a real open-ground/water record chosen by the field-blind selection rule.

## Judge checks

- **Gate:** `gate.py` gives PASS with no warnings.
- **Verify:** I re-ran `verify.sh` and it exited 0. All 20 tiles were re-decoded through the whole-file `decode_points` path with `struct.iter_unpack` extraction and matched the samples byte for byte. The header histograms, index fields and manifest totals were re-checked.
- **Build:** `build.sh` uses only local files. My own sha256 of two LAZ tiles matches the pins.
- **Bytes**, checked on all 20 samples with stdlib Python:
  - Values are 1..9 with no zeros.
  - Per tile, H0 is 0.34–1.25 bits and H1 0.32–1.10, except 0.008 for the open-valley tile.
  - 74–98% of values r>1 directly follow r−1.
  - Build stats record return number > number of returns on 0 points.
  - All 20 sample hashes are distinct.
- **Record order:** I decoded the first two chunks of 11TNK57309830. About 98% of GPS-time+channel groups form complete 1..k echo sequences. The file order is the contractor's delivered order, with three flight lines and both scanner channels interleaved within a chunk, so samples are natural records rather than concatenations or re-sorts.
- **Rights:** I opened the AWS registry YAML and the per-tile FGDC XML myself. No credentials appear in any script.
- **Novelty:** `novelty.py` was run with the URLs and terms, `--vocabulary`, and the type/instrument/archive keys. There is no return-number family locally, in the registry, or downstream. Same instrument line: 0. Same archive: 0.
- **Residual caveats, not blocking:**
  - Samples come only from the central and northern squares of the basin.
  - One sample is nearly constant. It is a genuine natural record making up 4.2% of bytes.
  - The quantity has a small alphabet and compresses heavily (zlib about 0.06–0.17).
