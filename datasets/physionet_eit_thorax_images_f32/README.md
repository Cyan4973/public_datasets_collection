# PhysioNet aeration-study thoracic EIT image sequences (FEM) — float32

Reconstructed thoracic **electrical impedance tomography** (EIT) images from
the PhysioNet project *Respiratory and heart rate monitoring dataset from
aeration study* v1.0.0 (Guy et al., 2024, DOI 10.13026/e4dt-f689, CC BY 4.0).
A Dräger PulmoVista 500 belt at axilla level recorded 32 × 32 relative
conductivity (aeration) change images at 50 Hz while 20 seated healthy
volunteers breathed through a full-face mask.

## Scope

The release has three EIT trials per subject: stepped PEEP, stepped PEEP with
breath holds, and forced expiratory manoeuvres (FEM). This recipe downloads
**all 20 FEM recordings** (`EIT_rawData/S01_FEM.bin` … `S20_FEM.bin`). It
emits the **17 that are continuous 50 Hz acquisitions**.

| | value |
|---|---|
| download | 20 files, 332,079,600 B, plus 4 small release files (53,591 B) |
| samples | 17 (one per retained recording), 3 excluded by rule |
| frames | 64,650 (3,000 to 8,400 per recording, median 3,250) |
| primary values | 66,201,600 float32 (264,806,400 B) |
| value range | -24.786 to 216.429 AU; exact zeros 2.86% |

**Exclusion rule.** A recording is excluded if any frame time-stamp step
exceeds 30 ms, i.e. it has dropped frames. Build and verify each derive this
from the source content. Exactly three recordings are excluded:

| recording | gaps (frame index, ms) |
|---|---|
| S02_FEM | (3853, 108), (4066, 103) |
| S08_FEM | (1775, 103), (1818, 97) |
| S09_FEM | (793, 120), (895, 105), (1266, 100), (1289, 91) |

The same three recordings are also off the common scale:

- Their single all-zero reference frame sits 1–4 frames before a gap.
- Nearly all of their frames sit on a large static baseline. The median
  per-frame maximum is 7,329–8,690 AU, against 23–67 AU in the 17 continuous
  recordings.
- The same subjects' PEEP trials are on the normal scale.

The cause is not documented upstream. Keeping these three would bundle a
regime about 150× larger into the family.

Either PEEP trial set alone would give about 1.39 GB of primary output, which
is over the 1 GB cap. Mixing a subject-ordered subset of PEEP_BH into the
recipe would be an arbitrary cut, so the PEEP trials are left out.

## Format and conversion

Each `.bin` file is a headerless sequence of 4358-byte little-endian frames,
laid out as in the authors' `Code/read_binData.m`:

| offset | bytes | field | used |
|---|---|---|---|
| 0 | 8 | time stamp (MATLAB reads 2 float32; the bytes are a float64 time-of-day in days, step 0.02 s) | validation only |
| 8 | 4 | float32 dummy | dropped |
| 12 | 4096 | **1024 float32 pixels** | **primary** |
| 4108 | 8 | int32 MinMax, int32 event marker | dropped |
| 4116 | 30 | event text | dropped |
| 4146 | 4 | int32 timing error | dropped |
| 4150 | 208 | 52 float32 Medibus values (fill: -1000 / -3.4e38) | dropped |

For every frame, the 1024 pixel words are copied unchanged. One sample per
recording holds all frames in stored order, with shape `frames × 32 × 32`.
Read row-major, each block is the caudal-cranial display image that
`read_binData.m` produces: its `reshape` + `rot90` + `flipud` amounts to a
transpose of MATLAB's column-major fill. The 29 corner pixels outside the
thorax mask are a native exact `0.0`. So is the one all-zero frame per
recording. It looks like the device's relative-impedance reference frame;
in 15 of the 17 retained recordings it carries a MinMax = -1 (breath-minimum)
marker.

Missing values: pixels have no sentinel. Any NaN or Inf is fatal, as are
checksum or frame-size mismatches, a time stamp outside `[0, 1)`, a median
frame step outside 19–21 ms, more than 5 exclusions, or a derived exclusion
set other than S02, S08 and S09. For retained recordings, these are also fatal:
a constant recording, more than 1% of frames repeating their predecessor, a
sampled frame with fewer than 256 distinct values, or a median per-frame
maximum above 1,000 AU. Nothing is imputed or partially dropped.

`verify.sh` re-derives the exclusions and re-decodes every frame with an
independent `struct` path. It re-packs each frame, byte-compares it with the
sample, and re-checks index fields, min/max from the stored float32,
per-sample and aggregate SHA-256, and the manifest totals.

## Not emitted

`subject-info.csv` (demographics, asthma, smoking and vaping history) and the
pressure/flow, ECG, PPG and heart-rate-belt files are not downloaded. The EIT
frames' wall-clock stamps, event text and Medibus fields are dropped.

## Run

```bash
bash staging/physionet_eit_thorax_images_f32/download.sh   # ~332 MB, resumable
bash staging/physionet_eit_thorax_images_f32/build.sh
bash staging/physionet_eit_thorax_images_f32/verify.sh
```

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/physionet_eit_thorax_images_f32/`.
