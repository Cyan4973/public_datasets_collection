# TUM VI EuRoC 1024 cam1 frames uint16 development

## Outcome

Accepted `tumvi_euroc_1024_cam_frames_u16`, from the official TUM Computer Vision Group release of the TUM VI visual-inertial benchmark (EuRoC/DSO export, 1024x1024, 16-bit).

These are the corpus's first terrestrial natural-scene camera frames at 16 bits. Existing 16-bit image families are:
- space detectors: Mastcam-Z, IRIS, JWST;
- microscopy: BBBC021/039, SEM;
- medical imaging;
- Earth-observation rasters.

The same host has two pre-autocollect recipes, `tum_rgbd_depth_u16` and `tum_rgbd_groundtruth_pose_f64`. They come from a different dataset (TUM RGB-D) and record different quantities: Kinect depth and mocap pose. Novelty is labelled `new_content_same_modality`. Measured breadth is OK: the nearest family is `soilgrids_clay_0_5cm_mean_i16` at distance 0.0904, with 1.02% compression loss.

## Source and rights

- Source: https://vision.in.tum.de/tumvi/exported/euroc/1024_16/dataset-<seq>_1024_16.tar, 28 uncompressed sequence tars of 3.37-61.4 GB each (551 GB total), Last-Modified 2018-04-17.
- Access: anonymous HTTPS range GETs of bytes `0..E-1` of each tar, where E is the end of the 8th cam1 PNG member. Each response must be a 206 with the pinned whole-tar size.
- Download: 205,860,343 bytes, 6.6-8.8 MB per prefix. Each prefix's SHA-256 is pinned in `scripts/prefix_sha256.tsv`. Member name, offset, size and last-IDAT CRC are pinned in `scripts/members.tsv`, which was resolved by header-only range reads (`discover.py`).
- License: CC BY 4.0. The dataset page states: "All data in the Visual Inertial Dataset is licensed under a Creative Commons 4.0 Attribution License (CC BY 4.0) and the accompanying source code is licensed under a BSD-2-Clause License." The same page links the exact `exported/euroc/1024_16/` directory. `download.sh` re-checks the sentence on every run.
- Citation: Schubert et al., "The TUM VI Benchmark for Evaluating Visual-Inertial Odometry", IROS 2018.
- Safety: indoor rooms, corridors and halls, and an outdoor university campus. Outdoor fisheye frames may show distant passers-by at low resolution. There are no annotations or identities.

## Shape and conversion

- Natural record: one cam1 frame, `mav0/cam1/data/<19-digit ns>.png`, which is a 1024x1024 16-bit grayscale PNG.
- Each tar's prefix contains only 4 directory headers and the first 8 cam1 PNG members in tar order. Tar order is not chronological, so the pinned frames spread across each recording: 53-1126 s between the earliest and latest pinned timestamp.
- The decoder is pure stdlib: strict chunk-CRC validation, IHDR fixed to 1024x1024 / depth 16 / colour type 0 / non-interlaced, zlib inflate, all five scanline filters (bpp=2), then big-endian to little-endian.
- Values are kept exactly as published. These are 12-bit sensor codes shifted into the top of 16 bits, so every value is a multiple of 16. There is no right shift, no rescaling, and the 2x2-binned 512_16 product is not used.
- Frames that are constant, or where one value covers more than 50% of pixels, would be skipped. None were.
- Output: one raw little-endian uint16 raster per frame, row-major (y, x).

## Accepted output

- Sequences: 28 (room1-6, corridor1-5, slides1-3, magistrale1-6, outdoors1-8), 8 frames each.
- Primary samples: 224 (0 skipped)
- Primary values: 234,881,024
- Primary bytes: 469,762,048
- Sample size: 1,048,576 values (2,097,152 bytes) each
- Value range: 0..65520. Per-frame minima are 0-1280 (median 384); per-frame maxima are all 65520.
- Distinct values per frame: 808-1031
- Most frequent value: 65520 (saturation) in 202 of 224 frames. The largest share of a frame taken by one value is 0.183 (outdoors7); the median is 0.022.
- zlsim: own compression ratio 3.21, verdict OK.

Erratum: the manifest `representation_notes` and the README say the per-frame minima run 0-1152. The realized figure is 0-1280. This is descriptive only; it does not affect scope, bytes, or any check.

## Judge checks

- `gate.py staging/tumvi_euroc_1024_cam_frames_u16`: PASS with no warnings (224 samples, median 1,048,576 values).
- I ran `verify.sh` myself: exit 0, with all 224 frames re-decoded and byte-compared, the index fields, skip list and manifest scope checked. build.sh and verify.sh contain no network calls. `scripts/selftest.py` passes. No `__pycache__` was written into the recipe.
- The download logs show a real fetch of all 28 prefixes at 15:58, with license and member validation passing. The 16:55 re-run hit the cache and matched the pinned SHA-256s.
- Bytes, inspected with `struct` on six sequences:
  - The low nibble is always zero.
  - Quantiles are plausible for real exposures.
  - Neighbouring pixels are strongly correlated: median absolute step 12-52 codes (in units of 16), in both directions.
  - Saturation is scene-dependent: 11% outdoors, 1.5-2.4% indoors.
  - Exact zeros: 2-12 pixels per frame in dark magistrale frames, on a continuous 64-code ladder.
- Independent decode: a decoder I wrote separately from `tumvi_lib` reproduces 6 samples byte for byte (room1, room6, slides2, magistrale5, outdoors6, outdoors8). All source rows use PNG filter type 1.
- Near-duplicates: 784 within-sequence pairs were compared on 64x64 point thumbnails. The closest has normalized MAD 0.20 and the median is 0.80. The 0.1 s room2 pair is 0.27, so it is not a duplicate. All 224 sample SHA-256s are distinct.
- Rights: I fetched the live dataset page and confirmed the CC BY 4.0 sentence and the link to the exact export directory. No credentials appear in any script.
- Novelty:
  - `novelty.py --url` matches only the host (pre-autocollect tum_rgbd recipes) and the staged TUM-VIE event candidate, which is not accepted.
  - `--type/--instrument/--archive` returns 0/0/0.
  - No terrestrial camera frames exist in numeric_datasets/16bit or transformer/source_data/le-u16.
  - The rule requiring user sign-off for a third acceptance from one host does not apply, because the earlier TUM recipes predate autocollect.
