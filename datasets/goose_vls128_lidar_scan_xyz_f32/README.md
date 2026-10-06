# GOOSE 3D val: Velodyne VLS-128 LiDAR sweep xyz (float32)

This recipe collects the per-point Cartesian coordinates of complete published
LiDAR revolutions from the GOOSE (German Outdoor and Offroad Dataset) 3D
validation split. All of them come from the roof-mounted 128-channel Velodyne
VLS-128 (Alpha Prime) on the MuCAR-3 research vehicle, a drive-by-wire
VW Touareg, driving unstructured off-road terrain in Bavaria. One sample is one
sweep file: an `N x 3` little-endian float32 array of `x, y, z` in metres,
interleaved per point in the source point order.

## Attribution and license (CC BY-SA 4.0)

The GOOSE dataset is by Peter Mortimer, Raphael Hagmanns, Miguel Granero,
Thorsten Luettel, Janko Petereit and Hans-Joachim Wuensche (Fraunhofer IOSB and
Universitaet der Bundeswehr Muenchen):

> P. Mortimer et al., "The GOOSE Dataset for Perception in Unstructured
> Environments", IEEE ICRA 2024, arXiv:2310.16788. https://goose-dataset.de/

License evidence:

- The download page https://goose-dataset.de/docs/setup/ says: "The GOOSE
  Datset is published under the CC BY-SA 4.0 License."
- The archive's own `LICENSE` member (20,138 bytes, CRC32 `ae93dc2c`,
  SHA-256 `28a9529c7d0bb4dc51f4bf5c116a3d16ef247a052f7591466768ddf563fd1cf5`)
  is the full "Attribution-ShareAlike 4.0 International" legal code.
  `download.sh` extracts it to
  `.data/downloads/goose_vls128_lidar_scan_xyz_f32/meta/LICENSE` and stops if
  it changes.

The derived sample files are adaptations of the GOOSE data. Anyone
redistributing them must credit the GOOSE authors as above, indicate the
changes (only the x, y, z fields of 64 selected sweeps are kept), and license
the result under CC BY-SA 4.0 (share-alike). See
https://creativecommons.org/licenses/by-sa/4.0/.

## Source and selection

- Archive: `https://goose-dataset.de/storage/goose_3d_val.zip`, 3,498,402,435
  bytes, Last-Modified 2025-03-19, ETag `"67da9ea9-d0856283"`. The CHANGELOG
  member reads "2024-07-26: Initial upload of GOOSE 3D with 9892 annotated
  LiDAR scenes."
- The archive holds 1,925 stored (method 0) members: 961
  `lidar/val/<seq>/<seq>__<frame>_<timestamp_ns>_vls128.bin` sweeps, 961
  labels, LICENSE, CHANGELOG and `goose_label_mapping.csv`. Every `.bin` size
  is a multiple of 16 (median 3,112,208 bytes, about 194k points).
- Selection: for each of the 8 val sequences, sort its sweeps by frame number
  (73 to 191 per sequence) and take the 8 centred in equal strata, i.e.
  indices `floor((2k+1) n / 16)`. The result, 64 sweeps, is pinned in
  `sources.tsv` (offset, byte range, size, CRC32). `discover.sh` documents
  how it was derived, and `download.sh` re-derives it from the live central
  directory on every run. The labelled scenes are already a sparse subsample
  of the 10 Hz stream, so consecutive selected sweeps of a sequence are 14 to
  270 seconds apart, not near-duplicate frames.
- Platform check: the GOOSE paper says "The GOOSE dataset was recorded on the
  UniBw Munich research vehicle MuCAR-3" and lists a single 128-channel roof
  Velodyne Alpha Prime (VLS-128 is that sensor's model code). Every val file
  ends in `_vls128.bin`. The oddly named `2022-07-22_flight` val sequence is
  the same recording day as the train sequence `2022-07-22_touareg_flight`,
  and Touareg is the MuCAR-3 vehicle. GOOSE-Ex (ALICE excavator, Spot robot,
  other sensors) is a separate download and is not used.

## Acquisition (`download.sh`)

The 3.5 GB archive is never downloaded whole:

1. A one-byte range GET checks liveness and range support.
2. The archive tail (bytes 3,498,085,530 to the end; 316,905 bytes) holds the
   three small metadata members, the central directory, the ZIP64 end
   record/locator and the EOCD. It is validated for 206 Content-Range, ETag,
   entry count and directory location, LICENSE/CHANGELOG CRC32 and text, and
   an unchanged selection.
3. Each pinned sweep is fetched as one exact byte range (local header plus
   payload). The local header is parsed and the payload starts after
   30 + local name length + local extra length. The local extra length is
   0 for every member, but it is read, not assumed. Name, method 0, sizes and
   CRC32 must match the central directory, and the size must be a multiple
   of 16. Only the payload is kept.

ZIP detail: the archive is under 4 GiB, but 1,214 central-directory records
store their local-header offset (above 2^31) in a ZIP64 extended-information
extra field. `scripts/goose_zip.py` resolves these offsets. Its `self-test`
exercises the parser on hand-built archives with and without ZIP64 offsets and
local extras, on a `zipfile`-written archive, and on CRC corruption.

Fetched bytes: 184,014,848 (member ranges) + 316,905 (tail). Kept under
`downloads/`: 184,006,576 bytes of payload, plus the tail and the three
metadata members.

## Build and verify

`build.sh` reads each payload as `N` points of four little-endian float32
fields (x, y, z, remission) and writes fields 0..2 of every point bit-exactly
as an `N x 3` float32 sample. Remission is integer-valued 0..255 stored as
float, so it is dropped rather than published as a widened integer. Labels
are not used.

Missing-value policy, identical in build and verify: upstream already omits
beams with no return, so `N` varies per sweep and no point lies within about
1 m of the sensor. Any NaN or infinity in any field, or any all-zero
`(0, 0, 0)` padding point, is fatal. Nothing is dropped, clipped, reordered or
imputed. The realized build found 0 non-finite fields and 0 all-zero points
in all 64 sweeps. Remission was integer-valued (0..255) in every sweep, which
confirms that dropping it loses no float32 content.

`verify.sh` does not reuse the build code. It checks each payload against
the CRC32 in `sources.tsv` and the SHA-256 in `payload_sha256.tsv` (recorded
from the first download), re-derives each sample by slicing 12 of every
16 source bytes, compares byte-for-byte, re-checks the
policy on raw IEEE-754 bit patterns, rejects constant samples or axes, checks
index fields, SHA-256 and min/max computed from the stored float32 values,
checks the sample-directory inventory, and checks the manifest's
`sample_count`/`total_size_bytes`.

Realized output: 64 samples (8 sequences x 8), 11,500,411 points, 34,501,233
float32 values, 138,004,932 bytes. The SHA-256 of all samples concatenated in
index order is
`a7cace02b1c8d5f2433d66d043ef1340eeaf5728d1aad63f396342597ddea5d6`.
Per-sample size ranges from 75,290 to 217,338 points (median 583,156.5
values). Coordinates span about ±200 m horizontally, the VLS-128 maximum
range; range runs from 1.0 m to 200.0 m and z from -70.9 m to +43.9 m. The
downloads take 184,354,632 bytes on disk and the samples 138,004,932 bytes.

## Known source quirks (kept as published)

`build_stats.json` records, for every sweep, azimuth coverage, maximum points
per azimuth degree, counter-rotation jumps (consecutive points whose
azimuth steps back by more than 5 degrees against the clockwise sweep) and
range extremes, so these can be audited.

- Partial revolutions: 57 of the 64 selected files cover at least 341 degrees
  of azimuth (52 of them all 360). Seven cover less:
  `2023-05-17_neubiberg_sunny` frames 0384, 0404, 0414, 0424, 0444 and 0454
  (156, 235, 324, 257, 197 and 249 degrees; 75k to 143k points), and
  `2023-03-03_garching_2` frame 0173 (323 degrees). Only 2 of the 8
  neubiberg_sunny picks are full revolutions. That recording evidently has
  packet loss or assembly problems: an unselected file of the same sequence
  spans about 60 degrees, and another (270,720 points) contains overlapping
  azimuth sectors. Only sunny frame 0414 shows a raised density among the
  picks (882 points per degree against a usual 600 to 650). These files are
  the same sensor, units and generation process. They are kept as the natural
  records the dataset publishes rather than filtered by an arbitrary
  coverage threshold.
- Locally non-monotone point order: 15 of the 64 sweeps, spread over
  aying_hills, aying_mangfall_2, garching_2, neubiberg_rain and
  neubiberg_sunny, contain 674 to 2,816 counter-rotation jumps (at most 3.2%
  of a sweep's points). The other 49 have none. Point order is preserved
  exactly as stored upstream.
- Ghost points: 18 sweeps contain points more than 20 m below the sensor
  (z down to -70.9 m), typical of reflection or multipath returns. They are
  kept unchanged.

Run from the repository root:

```bash
bash staging/goose_vls128_lidar_scan_xyz_f32/download.sh
bash staging/goose_vls128_lidar_scan_xyz_f32/build.sh
bash staging/goose_vls128_lidar_scan_xyz_f32/verify.sh
```
