# DIODE validation laser-scanner depth maps (float32)

Dense metric depth maps from the validation split of DIODE (Dense Indoor and
Outdoor DEpth; TTI-Chicago, University of Chicago, Beihang University). Each
depth map is a FARO Focus S350 terrestrial laser scan reprojected by the
publishers into one 1024x768 computational-camera view. Indoor and outdoor
scenes use the same scanner, camera model, unit (metres) and generation
pipeline. Upstream stores every map as a NumPy `.npy` array with dtype `<f4`
and shape `(768, 1024, 1)`.

One natural record is one camera view's depth map: 786,432 float32 values
(3,145,728 bytes), written unchanged as raw little-endian float32, row-major
768 x 1024.

## Source and rights

- Dataset page: <https://diode-dataset.org/>. Its License section says: "The
  DIODE dataset and the code is released using the MIT license."
  `download.sh` re-checks this sentence and the pinned MD5 on every run.
- Devkit: <https://github.com/diode-dataset/diode-devkit> (MIT, master
  `8b1765b7d801a5f5e2877c434ffe164e62ce8c90`). `intrinsics.txt` gives
  `[fx, fy, cx, cy] = [886.81, 927.06, 512, 384]`.
- Archive: `https://diode-dataset.s3.amazonaws.com/val.tar.gz`, 2,774,625,282
  bytes, publisher MD5 `5c895d09201b88973c8fe4552a67dd85`, S3 Last-Modified
  2019-08-01. The S3 ETag is a multipart ETag, not an MD5.
- Citation: Vasiljevic et al., "DIODE: A Dense Indoor and Outdoor DEpth
  Dataset", CoRR abs/1908.00463, 2019.

## Scope and view selection

The validation split has 771 views (325 indoors, 446 outdoor) in 6 scenes and
20 scans. These counts match the site's statistics table and the official
`data_list.zip` CSVs, and the build asserts them against the archive. All views
of a scan come from one scanner position, at yaw 0-350 degrees and pitch
0-50 degrees in 10-degree steps. Because the camera's field of view is
60 x 45 degrees, neighbouring views overlap heavily.

The build therefore keeps only views that are nearly disjoint within their
scan:

1. Within each scan, visit the views in ascending `SHA-256(view_id)` order.
   This is a deterministic pseudo-random order, which spreads the kept views
   across pitch.
2. Cast a 64 x 48 grid of pixel-centre rays through the devkit camera at the
   view's yaw and pitch (taken from the file name), with no roll. Count how
   many rays land inside another view's image.
3. Keep the view only if at most 153 of 3,072 rays (about 5 %) are shared, in
   either direction, with every view already kept for that scan.

Selection depends only on member names. On the official enumeration it keeps
85 views (38 indoors, 47 outdoor). Every scan contributes 3-6 views, and all
pitches 0-50 degrees are represented. That gives 85 x 786,432 = 66,846,720
values, or 267,386,880 bytes.

```bash
python3 staging/diode_val_laser_depth_f32/scripts/diode_depth.py predict --data-list data_list.zip
```

`data_list.zip` is the official enumeration
(`https://diode-1254389886.cos.ap-hongkong.myqcloud.com/data_list.zip`). It
was used only while authoring the recipe, to predict the count; build and
verify derive everything from the archive itself.

## Missing values

`0.0` is the source encoding for "no valid return", for example sky. The
publisher reports return density of 99.6 % indoors and 66.9 % outdoors.
Zeros are preserved unchanged.

`verify.sh` reads each selected view's `*_depth_mask.npy`, whose dtype is
either `<f4` or `<f8`, and checks two things: every mask value is 0 or 1, and
every zero-depth pixel is flagged invalid. Some nonzero depths are also flagged
invalid by the mask, for example a few sub-0.6 m returns. They are kept as
published; the mask is not applied, and it is not emitted.

The following are fatal and are never dropped or imputed:

- non-finite or negative values
- fewer than 1 % nonzero pixels in a view
- fewer than 1,000 distinct values in a view
- values above a 1,000 m sanity bound

## Pipeline

- `download.sh` runs four steps:
  1. Check the license sentence and MD5 on the dataset page.
  2. Liveness and size check with a one-byte range GET.
  3. Resumable transfer: `curl -C -`, stall abort at <1 KB/s for 120 s, and an
     outer retry loop, writing to `val.tar.gz.part`.
  4. Validate the result with `scripts/check_archive.py`: exact size,
     publisher MD5, gzip magic, tar headers in the first 8 MiB, and the first
     depth NPY header. Only then is the file renamed.
- `build.sh` (`scripts/diode_depth.py build`) streams the archive twice with
  `tarfile` mode `r|gz` and never extracts it, since extracted val is about
  5 GB. Pass 1 builds the inventory, re-hashes MD5 over the exact streamed
  bytes, checks the layout and counts, and selects views. Pass 2 parses each
  selected `*_depth.npy` header (`<f4`, C order, `(768, 1024, 1)`) and writes
  the payload unchanged. It also writes
  `index/diode_val_laser_depth_f32/samples.jsonl` (required fields plus
  environment, scene, scan, view, yaw, pitch, source member, SHA-256 and value
  statistics) and `filtered/diode_val_laser_depth_f32/ingest_stats.json`.
- `verify.sh` (`scripts/diode_depth.py verify`) re-inventories the archive and
  re-checks MD5. It checks the greedy-selection property against the full
  inventory: walking each scan in hash order, a view is indexed exactly when
  it is clear of all earlier indexed views. It then re-parses NPY headers with
  an independent regex parser and byte-compares every sample with its archive
  payload. Finally it runs the mask check, recomputes per-sample statistics
  from the written files, and matches the manifest totals.
- `python3 scripts/diode_depth.py selftest --workdir /tmp/...` builds and
  verifies a synthetic archive with the same layout. It includes mixed
  `<f4`/`<f8` masks, a corrupted sample, which must be rejected, and a wrong
  MD5, which must be rejected.

Local footprint is about 2.77 GB of download plus about 0.27 GB of samples.

## Realized output (build of 2026-10-06)

The download was 2,774,625,282 bytes, with MD5 matching the publisher. The
archive inventory matched the expected counts: 771 views (325 indoors, 446
outdoor) in 20 scans.

| Measure | Indoors | Outdoor |
| --- | --- | --- |
| Samples | 38 | 47 |
| Zero (no-return) fraction per view, min / median / max | 0 / 0.09 % / 0.85 % | 0.22 % / 13.5 % / 80.5 % |
| Nonzero depth, p1 / p50 / p99 | 0.63 / 2.38 / 14.5 m | 1.79 / 9.61 / 61.4 m |
| Per-view maximum, min / median / max | 1.4 / 151.7 / 283.6 m | 85.6 / 212.8 / 295.0 m |

Selection kept 85 samples covering all 20 scans. By pitch: 0° 31, 10° 13,
20° 10, 30° 15, 40° 9, 50° 7. The output is 85 x 786,432 = 66,846,720 float32
values, or 267,386,880 bytes.

Across all samples:

- 11.84 % of values are zero.
- Positive depths range from 7.3e-12 m to 295.0 m.
- Each view has 377k-763k distinct values.

The validity masks of the selected views are 70 `<f4` and 15 `<f8`. They mark
8,464,792 pixels invalid. Of those, 548,014 carry a nonzero depth; these are
kept as published. No zero-depth pixel is marked valid.

Indoor views reach 100-280 m where the scanner sees out through windows or
doors. Build and verify each take about one minute.

## Limits

- The validation split covers only 6 scenes and 20 scans, so scene diversity
  is moderate. The train split (81 GB) is far beyond the download budget.
- Indoor and outdoor depth distributions differ in typical scale: the median
  nonzero depth is 2.4 m indoors and 9.6 m outdoors. They overlap heavily,
  and indoor views also contain long returns. Both are kept as one series
  because unit, float32 encoding, sensor, camera model and generation process
  are identical. Splitting them would mean two series of the same quantity.
- One outdoor view (and a few others in part) is dominated by sky with no
  return; the worst view is 80.5 % zeros. Views are not filtered on content
  beyond the 1 % nonzero floor.
- The depth maps are a published reprojection of 360-degree scans. That
  reprojection is the upstream product; nothing is re-rendered locally.
