# comma2k19 global-pose ECEF camera positions (float64)

This recipe collects the per-frame Earth-centred, Earth-fixed (ECEF) position
of the road-facing camera for every one-minute segment of
[comma2k19](https://huggingface.co/datasets/commaai/comma2k19). comma.ai
estimated the poses with a tightly coupled INS/GNSS/vision optimizer that runs
on raw GNSS processed by their open-source Laika library. Each segment
publishes `global_pose/frame_positions` as a NumPy `.npy` array with dtype
`'<f8'`, C order and shape `(N, 3)`, one row per 20 Hz video frame (x, y, z in
metres).

One sample is one segment's array, written unchanged as little-endian
row-major float64: `samples/<id>/comma2k19_frame_positions_ecef_f64/<dongle>_<route-start>_seg<NN>.bin`.

## Why float64

Coordinates sit near (-2.71e6, -4.26e6, 3.88e6) m and carry sub-millimetre
fractional digits, so they need the full 53-bit mantissa. This is the
published dtype, not a widening. Consecutive rows differ by about 1.4 m at
highway speed, which makes the material a smooth, high-magnitude 3-vector
trajectory.

## Scope

- Source: `commaai/comma2k19` on Hugging Face, pinned to commit
  `4bff77c7254c654c28d4c2726186b4e825adccee`, `raw_data/Chunk_1.zip` …
  `Chunk_10.zip` (ZIP64, 8.7–9.9 GB each, 94.6 GB in total).
- Every segment in all ten chunks is kept: **2,035 segments**, 178 routes,
  two recording devices (dongles `99c94dc769b5d96e`: 1,653 segments;
  `b0c9d2329ad1606b`: 382), drives from 2018-05-01 to 2018-11-19.
  The dataset card's "2019 segments" is the dataset's name and rounded count.
  The archives actually contain 2,035 segment directories, each with a
  complete `global_pose/` folder.
- Expected output: 7,291,422 float64 values in 58,331,376 bytes. Segments run
  from 194 to 1,202 frames, with a median of 1,200 (3,600 values). Two
  segments fall below 1,000 values (194 and 222 frames). They are kept as
  natural records; the median floor is unaffected.
- Excluded on purpose: `frame_times`, `frame_gps_times`, `frame_orientations`,
  `frame_velocities`, and all `processed_log` (CAN, IMU, GNSS), `raw_log`,
  video and preview members. They are other quantities, or float32/integer
  data widened to f64, and would be same-source column slices.

## How the download works

The full archives total ~94.6 GB, but the recipe needs only ~58 MB of them.
`download.sh` does all network I/O with curl:

1. Fetch the dataset card at the pinned revision. Check its SHA-256 and
   `license: mit`.
2. For each chunk, send a resolve-URL `HEAD` and check `x-repo-commit`,
   `x-linked-size` and `x-linked-etag` (the LFS SHA-256) against
   `chunks.tsv`. Fetch the last 4 KiB and check that the ZIP64 EOCD and its
   locator match the pinned central-directory offset, size and entry count.
   Fetch the central directory (1.7–2.0 MB) and check its pinned SHA-256.
3. Parse each central directory, reading the ZIP64 extra field (0x0001) for
   sizes and offsets above 4 GB, into exact member ranges. A range starts at
   the member's local header and ends just before the next local header in
   offset order. The local extra field (28 bytes, UT + ux) differs from the
   central-directory copy, so header lengths are re-read from the local
   header.
4. Fetch the 2,035 ranges with `curl --range` (4 in parallel, retries,
   `--max-filesize` guarding against a server that ignores ranges). Members
   already present at the exact length are skipped, so re-runs resume.
5. Validate every member: local header against the central directory
   (name, method, flags, CRC32, sizes), raw-deflate inflate ending exactly at
   the boundary, CRC32, NPY header (v1/v2/v3 accepted; `'<f8'`, C order,
   `(N,3)`), body length `N*24`, finite values, `6.3e6 < |r| < 6.4e6` m, and
   no all-zero rows. Transport-corrupt members are deleted and refetched for
   up to 6 rounds. A semantic violation in a CRC-valid member is fatal.

Downloaded bytes: 19,049,072 (central directories) + 38,833,765 (member
ranges) + about 46 KB (card, tails, headers, plans).

## Realized build (2026-10-05)

- Download: 58,643,956 bytes on disk in 660 s. All 2,035 members were
  fetched and validated in the first round (no retries, no corrupt members).
- Output: 2,035 samples, 7,291,422 values, 58,331,376 bytes. Frames per
  segment run 194–1,202 (median 1,200). Aggregate decoded SHA-256:
  `62e64e8b3194568ef3b14061301a9cd64801958e775184e1ee1b8cb2df35109f`.
- Global value range: -4,274,011.95 to 3,882,266.05 m. None of the values in
  a 50-sample check round-trip through float32.
- Inter-frame step: median 1.37 m (about 99 km/h). The 99th percentile of
  per-segment maximum steps is 3.30 m.
- One segment is step-flagged (`99c94dc769b5d96e|2018-07-02--19-08-27/10`).
  It has a single 4.60 m step at frame 723 among neighbouring 1.53 m steps,
  consistent with a short frame-time gap. It is kept and flagged.
- 177 segments (8.7%) are near-stationary, with median step < 5 cm (stopped
  traffic or parked). They are real one-minute records and are kept.

## Build and verify

`build.sh` works from local files only. It re-inflates each member, re-checks
CRC32 and the NPY contract, and writes the array body unchanged. It rejects
duplicate payloads and enforces the pinned totals. It records per-sample
`min`/`max` from the stored float64, the median and maximum inter-frame step,
and the source member and CRC in `.data/index/<id>/samples.jsonl`.
Inter-frame steps above 4 m (80 m/s, implausible for a car) are flagged
(`step_flagged`) in the index and in `ingest_stats.json`, never dropped.

`verify.sh` independently re-derives the member set from the downloaded
central directories and re-inflates every member. It re-parses NPY headers
with a separate parser, compares every sample byte, and re-checks finiteness,
ECEF radius, non-constant components and payload uniqueness. It reconciles
index fields, totals, the manifest and the build's aggregate SHA-256.

```bash
bash staging/comma2k19_global_pose_ecef_positions_f64/download.sh
bash staging/comma2k19_global_pose_ecef_positions_f64/build.sh
bash staging/comma2k19_global_pose_ecef_positions_f64/verify.sh
```

Set `COMMA2K19_PARALLEL` to change the range-request concurrency (default 4;
Hugging Face allows 3,000 resolver requests per 5 minutes unauthenticated).
`python3 scripts/comma2k19_pose.py selftest` exercises the ZIP64, deflate,
CRC and NPY parsers on synthetic inputs, and `download.sh` runs it first.

## License

MIT. The official `commaai` dataset card at the pinned revision declares
`license: mit` in its YAML front matter (HF tag `license:mit`).
`download.sh` re-checks this. Cite: Schafer, Santana, Haden, Biasini,
*A Commute in Data: The comma2k19 Dataset*, arXiv:1812.05752 (2018).
The upstream GitHub repository was not reachable from the collection
environment, so the HF card is the only license evidence checked first-hand.

## Location-privacy note

comma.ai intentionally published these trajectories under MIT and trimmed
them to a ~20 km stretch of California I-280 between San Jose and San
Francisco. They carry no names, plates, addresses or trip endpoints. Devices
appear only as anonymous 16-hex-digit dongle ids. The positions are still
commute traces of two vehicles on a public highway. This recipe emits only
the positions: no video, imagery, CAN, or anything off the published
highway section.

## Nearest families

- `tum_rgbd_groundtruth_pose_f64`: indoor handheld-camera motion-capture
  translation in a local frame (metre-scale values, one 3,000-pose sequence).
  Different generation process, magnitude and scale.
- `noaa_cors_rinex_observations_f64`: raw GNSS observables (pseudorange,
  carrier phase, C/N0) from static reference stations. Those are inputs to
  positioning, not solved positions.
- `noaa_marinecadastre_ais_2024_01_01_f32`: vessel AIS report fields
  (lat/lon degrees and others) as float32 column streams, at irregular
  report times.
- `hsl_gtfs_static_schedule_numeric` `shapes_lat_lon_f64`: static transit
  route polylines in degrees, with no time lattice.

No accepted recipe, registry entry or downstream family uses comma2k19, or
fused-estimator vehicle trajectories in ECEF metres on a fixed 20 Hz lattice
(`tools/autocollect/novelty.py --terms comma2k19 commaai ecef laika`).
The novelty kind is new source with a new quantity in a known
trajectory/coordinate modality, not a new modality.
