# LiDAR for Scotland Phase I scan angle rank int8 development

## Outcome

Accepted `srsp_scotland_phase1_lidar_scan_angle_i8`. Each sample is the complete LAS **Scan Angle Rank** field of one pinned 1 km LiDAR for Scotland Phase I LAZ tile, stored as native signed int8 in file point order.

This is the corpus's first scan-angle family at any width. The nearest relatives are the `dc_lidar_2015_*` recipes (classification u8, intensity u16, GPS time f64), which come from a different survey and carry different fields. Novelty kind: new quantity (and new source) in the known airborne-LAS modality.

## Source and rights

- Source: Scottish Public Sector LiDAR Phase I (Scottish Government, SEPA, Scottish Water). Blom flew it in March 2011 to May 2012 at about 2 points/m², across 10 collection areas.
- Bucket: `https://srsp-open-data.s3.eu-west-2.amazonaws.com/`, prefix `lidar/phase-1/laz/27700/gridded/` (12,464 tiles, 68.5 GB, listed 2026-10-08).
- Pinned download: 88 tiles, 433,958,092 bytes. `scripts/tiles.tsv` pins each tile's key, size, S3 ETag (MD5 or 8 MiB multipart), sha256 and point count.
- License: Open Government Licence v3. The portal API (`https://api.remotesensing.data.gov.scot/search/collection/scotland-gov/*`) gives these terms for collection `scotland-gov/lidar/phase-1/laz`:
  - useConstraints: "Crown copyright Scottish Government, SEPA and Scottish Water (2012). Open Government Licence v3"
  - limitationsOnPublicAccess: "No limitations on public access"
- Phase II (`scotland-gov/lidar/phase-2/laz`) is under the Non-Commercial Government Licence. `download.sh` and `validate_downloads.py` refuse any key outside `lidar/phase-1/laz/`.

## Shape and conversion

- Natural record: one 1 km British National Grid tile becomes one sample, covering all of its points.
- Decoding: `tools/laz/laszip.py` `iter_chunks` turns each tile into 28-byte PDRF-1 records. LASzip compressor 2, POINT10 v2 + GPSTIME11 v2, 50,000-point chunks.
- Byte 16 of each record (Scan Angle Rank, signed char, degrees) is copied unchanged. No points are dropped and no values are remapped.
- Selection (`scripts/discover.py`, maintainer-only):
  - Several Phase I areas were delivered with the scan-angle byte zeroed in every point: HY, NH, NJ, NK, western NN, NR8xxx and northern NO.
  - Discovery took 128 candidates evenly spaced over the sorted key list and kept the 88 whose first chunk is not constant. The kept tiles are in eastern NN, NO, NS, NT, NX and NY.
  - The 40 dropped candidates are logged in `scripts/discovery_log.tsv`.
- Degeneracy policy (fatal in both build and verify): fewer than 5 distinct values, one value above 50% of points, a span under 10°, or any value outside ±90.

## Accepted output

- Primary samples: 88
- Primary values: 151,122,545
- Primary bytes: 151,122,545
- Sample size: minimum 124,504 values, median 1,759,592.5, maximum 3,531,022
- Value range: -29..+29 degrees, 59 distinct values
- Per-tile span: minimum 15, median 50, maximum 58 degrees
- Zeros: 2.04% overall, at most 4.5% in any tile
- Largest single-value share in any tile: 15.5% (NS4212, a 124,504-point edge tile)
- Generating software: 71 tiles TerraScan, 17 re-zipped by LASzip DLL 2.4, all with the same PDRF-1/28-byte layout
- Aggregate SHA-256 of samples concatenated in index order: `fa3efcb8e22699ad3e5edd178f3798ab4868804c4d0fce22374a318c9bf46e3f`
- Breadth (driver zlsim): verdict OK. The nearest family is `noaa_isd_lite:isd_day` at feature distance 0.0788 with loss 0.0. That pair is compression-equivalent but feature-distinct, and the rule needs both to call it redundant.

## Judge checks

- `gate.py` PASS, no warnings.
- `verify.sh` run by me: exit 0 in 1m45s. All 88 samples were re-decoded from local LAZ and are byte-identical, and the realized stats match the manifest.
- `build.sh` uses only local files. Network access is curl in `download.sh` and the maintainer-only `discover.py`. No credentials anywhere.
- All 88 local LAZ files match the pinned sha256 and size, recomputed independently.
- Field check: I decoded the first chunk of NS5048 to full PDRF-1 records.
  - Point source ID 122 is dominant, classes are 1 and 2, user data is 0.
  - GPS time is monotonic: 2 backward steps in 50,000.
  - The scan angle sweeps smoothly from 12 to -24, and within the flight line it correlates with Y (r = 0.74). That is a cross-track scan over an E–W line, which confirms byte 16 is the scan angle.
- Byte inspection of all 88 samples:
  - Distribution is near-uniform across -24..+23.
  - About 96% of consecutive deltas are 0 and about 4% are ±1.
  - Up and down steps balance in NN, NO, NS, NT and NX, so the same zigzag mirror sweep appears in every area tested.
  - Order-0 entropy is 5.2–5.6 bits/value and delta entropy 0.22–0.30 bits/value. The material compresses very well, but it is genuine signal whose run lengths vary with terrain and returns.
- Exclusion check: I range-read the middle and last chunks of two dropped tiles, NJ7150 and NO6595. Every point was 0, so excluding these areas removes an unpopulated field, not real data.
- Rights: I fetched the portal collection API myself and confirmed OGL v3 for phase-1/laz and NCGL for phase-2/laz. The bucket's `lidar/` prefixes mirror the portal collections.
- Novelty: `novelty.py` URL and term search matched only this candidate's own staging and ledger entries. No scan-angle family exists locally or downstream at any width, and no other recipe uses the instrument line or archive.
