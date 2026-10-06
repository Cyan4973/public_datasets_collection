# DIODE validation laser-scanner depth float32 development

## Outcome

Accepted `diode_val_laser_depth_f32`: native float32 metric depth maps from the
validation split of DIODE (Dense Indoor and Outdoor DEpth; TTI-Chicago,
University of Chicago, Beihang University). Each sample is one publisher-made
camera view of a FARO Focus S350 terrestrial laser scan, kept exactly as
published.

This is the first float32 dense depth-raster family in the local corpus. The
downstream corpus has none at 32-bit either. Related families differ in
material or width:

- `tum_rgbd_depth_u16`: Kinect structured-light integer depth at 16-bit.
- `cartographer_backpack2d_hokuyo_ranges_f32`: planar 1D laser range-scan
  sequences.
- `goose_vls128_lidar_scan_xyz_f32`: 3D point-coordinate lists.

Novelty is therefore recorded as `new_source`, not `new_quantity`. Depth and
laser distance in metres already exist in the corpus. What is new is the
source and the dense 2D perspective depth-raster structure at 32-bit.

## Source and rights

- Archive: `https://diode-dataset.s3.amazonaws.com/val.tar.gz`
  - 2,774,625,282 bytes; publisher MD5 `5c895d09201b88973c8fe4552a67dd85`
  - S3 Last-Modified 2019-08-01
  - Anonymous HTTPS, not requester-pays
  - The S3 ETag is multipart and is not used.
- License: MIT. The License section of diode-dataset.org reads: "The DIODE
  dataset and the code is released using the MIT license." The sentence covers
  the dataset itself.
  - The same page's download table links this exact S3 object with this MD5.
  - The devkit (`diode-dataset/diode-devkit`) is MIT as well.
  - `download.sh` re-checks the sentence and the MD5 on every run.
- Camera: devkit `intrinsics.txt` gives `[fx, fy, cx, cy] = [886.81, 927.06, 512, 384]`.
- Citation: Vasiljevic et al., *DIODE: A Dense Indoor and Outdoor DEpth
  Dataset*, CoRR abs/1908.00463, 2019.

## Shape and conversion

Each natural record is one `*_depth.npy` member: a `(768, 1024, 1)` C-order
`<f4` tensor holding 786,432 values (3,145,728 bytes) in metres. The archive is
streamed twice with `tarfile` mode `r|gz` and never extracted (extracted size is
about 5 GB).

1. **Pass 1 (inventory).** It hashes MD5 over the exact streamed bytes. It then
   asserts 325 indoor and 446 outdoor views in 10 + 10 scans, each view having
   a png, a depth and a mask member. These counts match the site's Partitioning
   table.
2. **Selection.** Within each scan, views are visited in SHA-256(view_id)
   order. A view is kept only if, on a 64x48 pixel-centre ray grid through the
   devkit camera (yaw and pitch from the file name, no roll), at most 153 of
   3,072 rays are shared in either direction with every view already kept.
   This removes the heavy overlap of the upstream lattice: 20-degree yaw steps
   per pitch against a 60x45-degree field of view.
3. **Pass 2 (extraction).** It asserts the NPY header and writes each payload
   unchanged as raw little-endian float32, row-major 768x1024.

Exclusions and missing values:

- RGB PNGs, validity masks (mixed `<f4`/`<f8`) and normals are excluded.
- 0.0 is the source code for "no return" and is preserved.
- Mask-invalid nonzero depths (for example sub-0.6 m returns) are kept as
  published.
- Non-finite or negative values, views with under 1% nonzero pixels, views with
  under 1,000 distinct values, and depths above 1,000 m are fatal.

## Accepted output

| Measure | Value |
| --- | --- |
| Upstream population | 771 views (325 indoors, 446 outdoor), 6 scenes, 20 scans |
| Primary samples | 85 (38 indoors, 47 outdoor); every scan contributes 3–6 |
| By pitch | 0°: 31, 10°: 13, 20°: 10, 30°: 15, 40°: 9, 50°: 7 |
| Primary values | 66,846,720 (786,432 per sample) |
| Primary bytes | 267,386,880 |
| Zero (no-return) fraction | 11.84% overall; indoors 0.15%, outdoor 21.3% |
| Outdoor per-view zero fraction | median 13.5%, max 80.5%; 7 views above 50% |
| Positive depth range | 7.3e-12 m to 294.99 m |
| Per-view maximum, indoors | min 1.4 m, median 151.7 m, max 283.6 m |
| Per-view maximum, outdoor | min 85.6 m, median 212.8 m, max 295.0 m |
| Distinct values per view | 148,429–761,366 (median 705,007) |
| Masks of the selected views | 70 `<f4`, 15 `<f8`; 8,464,792 pixels invalid, of which 548,014 carry nonzero depth |
| Download | one transfer, about 93 s |

The README's "377k–763k distinct values" understates the minimum. The realized
minimum is 148,429, in the 80.5%-sky view `00023_00200_outdoor_210_030`.

## Judge checks

- **Gate:** `gate.py` PASS with no warnings (85 samples, median 786,432 values,
  width 32).
- **Verify:** I reran `verify.sh` and it passed in 1:05. It re-inventoried the
  archive and re-checked the MD5. It checked the greedy-selection property over
  all 771 views, byte-compared all 85 samples with the archive through an
  independent regex NPY parser, and checked the masks: no zero-depth pixel is
  marked valid. Index statistics and manifest totals were re-derived.
  `build.sh` and `verify.sh` read only the local archive.
- **Bytes:** I inspected samples with `array`/`struct`.
  - All files are 3,145,728 B, and all 85 sha256 hashes are unique.
  - The low 16 bits are zero only at the 0.0 code, there are 256 distinct low
    bytes, and float exponents 126–132 are in use. This is honest float32, not
    widened or quantized.
  - Rows are spatially smooth.
  - Indoor log2 mass lies mostly between 1 and 8 m; outdoor between 3 and 45 m.
  - Outdoor zeros sit in the top image band (sky): median 41% in the top 96
    rows versus 0.2% in the bottom 96.
  - Below 0.6 m lie 0.725% of indoor values and 0.179% of outdoor values.
- **Near-duplicates:** I streamed every view of scans 00183 (73 views) and
  00193 (51 views) from the archive.
  - Exact-value sharing between views rises steadily with the recipe's modelled
    overlap: 2.5% at no overlap, 10–14% at 50–70%, and up to 27% for the
    closest pairs.
  - Pairs of kept views share 0–9% (scan 00183) and 0.1–4% (scan 00193),
    against a 1.5–3.6% baseline from opposite-facing views.
  - The selection therefore removes overlap in practice, not just on paper.
- **Rights:** I fetched diode-dataset.org myself and read the MIT sentence,
  which names the dataset. The download table links this exact S3 object and
  MD5. The devkit LICENSE is MIT. No credentials appear in any script, and no
  RGB or personal data is emitted.
- **Novelty:** `novelty.py` found no URL match. The only depth-raster hit is
  `tum_rgbd_depth_u16` (16-bit Kinect). The 32-bit laser-related hits are GOOSE
  point coordinates and Cartographer planar range scans, which have different
  structures.
- **Homogeneity:** One sensor, one camera model, one reprojection pipeline and
  one metre unit. Indoor and outdoor scales differ by about 4x but overlap on
  one axis. This follows the `tartanair_optical_flow_f32` precedent of one
  family across varied environments.
- **Volume:** 267 MB is essentially the non-overlapping population of the val
  split. All 771 views would be about 2.4 GB, over the cap. The train split is
  81 GB. The 0.27/2.77 GB extraction ratio is unavoidable with a non-seekable
  gzip tar, and the kept signal is large.
