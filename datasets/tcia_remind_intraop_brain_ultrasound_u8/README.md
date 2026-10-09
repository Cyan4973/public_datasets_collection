# TCIA ReMIND intraoperative 3D brain ultrasound volumes (uint8)

14 complete reconstructed 3D B-mode ultrasound volumes from TCIA's *Brain
Resection Multimodal Imaging Database* (ReMIND), one per patient
(ReMIND-001 to ReMIND-018). All come from the same surgical stage: the
`US_pre_dura` sweep, acquired after craniotomy and before the dura is opened,
during image-guided tumour resection in the AMIGO suite at Brigham and
Women's Hospital (2018-2022). Each sample is the complete DICOM Pixel Data
volume, copied byte for byte as uint8 (values 0-255). The one exception is the
trailing even-length pad byte, which is dropped.

## What the numbers are

Each volume was reconstructed from a tracked freehand 2D ultrasound sweep. It
was saved as NRRD and converted by TCIA with PixelMed `NRRDToDicom` into one
Multi-frame Grayscale Byte Secondary Capture object (8 bits allocated and
stored, MONOCHROME2, identity rescale, lossless, Explicit VR Little Endian).
Voxel values are the 8-bit echo intensities of the published volume. The
sample layout is frame-major, then row, then column, and `sample_shape` in the
index gives `[frames, rows, columns]`.

Geometry is consistent across the pins. In-plane spacing is 0.125-0.147 mm
and slice spacing 0.47-0.50 mm. Shapes range from 77x587x763 to 222x611x747,
and per-volume spacing is recorded in `pinned_series.tsv` and the index.

**Zero background.** Each volume's bounding box is filled with zero outside
the swept acquisition cone/fan. Realized per-volume zero fractions are
0.471-0.626 (aggregate 0.5629). This zero region is the scan geometry, not a
no-data fill over missing measurements, and the voxel-level boundary of the
cone is part of the material. It is kept and not cropped.

A row-run analysis supports this. It checked every ~1/12th frame of every
volume. 98.7-99.7% of zero voxels lie in contiguous zero runs at the left
and right ends of image rows, or in fully blank rows: the outside of the fan
and the near-field rows above its apex. Only 0.3-1.3% of zeros lie inside the
cone, and those continue smoothly into the values 1, 2 and 3, which are
dark echoes. Some volumes also begin or end with fully blank frames. These
are bounding-box padding along the sweep direction, up to 8 leading and 7
trailing frames, 14 at most in one volume (ReMIND-001: 7+7 of 222;
ReMIND-012: 8+6 of 197). They are
counted in the index as `all_zero_frames`.

`tools/autocollect/gate.py` warns that 1 of 14 scanned samples is constant.
That is a sampling artifact. For files over 64 MiB the gate reads only about
71 KB at the start and 71 KB at the midpoint. In `us_pre_dura_01` both
windows fall in zero background: the leading blank frames, and the top rows
of the middle frame above the cone apex. Every volume has all 256 byte values.
Every index row records `zero_fraction`, `mode_value`, `mode_fraction` and
`all_zero_frames`. verify.sh fails any volume that is more than 90% zero,
mostly blank or repeated frames, or has fewer than 64 distinct values.

## Breadth measurement (zlsim)

An earlier builder-side run of `tools/autocollect/zlsim.py gate` (before
commit a16dfc2) gave verdict WEAK. It matched `covertype_uci` one-hot columns
at distance 0.0, with mode_share 1.0. That result was a sampling artifact:
the tool fingerprinted only the first 256K values of each file, and in 11 of
the 14 volumes those prefixes are pure cone/bounding-box background. Commit
a16dfc2 fixed zlsim to use four windows centred at 1/8, 3/8, 5/8 and 7/8 of
each sample, plus central compression chunks. The calibration report addendum
names this candidate as one of the affected cases. The stale pre-fix candidate
cache entry was removed, so the driver's gate re-measures from scratch.

Post-fix builder-side run (2026-10-08, fresh candidate cache): verdict
**OK**, not redundant, no fill warning, mode_share 0.667, own held-out ratio
3.139. The margin is thin. Several existing compressors are within the 3%
loss threshold, and only the feature distance keeps the candidate above the
0.05 line:

| neighbour | distance | loss |
|---|---|---|
| `mpc_landsat_c2_l1_mss_dn_u8` | 0.0522 | -0.0033 |
| `sevir_vil_storm_events_u8` | 0.0555 | 0.2143 |
| `zenodo_hc18_fetal_head_ultrasound_u8` | 0.0576 | 0.0145 |
| `nasa_pds_cassini_radar_bidr_sigma0_u8` | 0.0740 | 0.0361 |
| `bbbc007_fluorescence_u8` | 0.1008 | -0.0003 |

So the material is OK-but-near: compression-equivalent to Landsat MSS DN,
HC18 and BBBC007, and statistically just outside the redundancy distance.
The recipe keeps the source voxel order and does not crop or reorder to
influence the measurement.

## Run

1. `bash staging/tcia_remind_intraop_brain_ultrasound_u8/download.sh`:
   972,784,450 bytes in 14 whole-object GETs of 34.5-101.4 MB each, plus one
   ~270 KB metadata listing
2. `bash staging/tcia_remind_intraop_brain_ultrasound_u8/build.sh`
3. `bash staging/tcia_remind_intraop_brain_ultrasound_u8/verify.sh`

Outputs:

- `samples/tcia_remind_intraop_brain_ultrasound_u8/remind_us_pre_dura_volume_u8/us_pre_dura_NN.bin`:
  14 files, 972,270,283 bytes total (median about 69 MB). Realized on
  2026-10-08: every volume spans 0-255 with all 256 values present
  (download was 973,063,607 bytes in 195 s).
- `index/tcia_remind_intraop_brain_ultrasound_u8/samples.jsonl`
- `filtered/tcia_remind_intraop_brain_ultrasound_u8/ingest_stats.json`

## Selection

`pinned_series.tsv` fixes the 14 series. Per series it records the series,
SOP, study and pseudonymous patient IDs, the file size, the header length and
SHA-256, the shape, and the pixel and slice spacing. `discover.sh` and
`discover.py` reproduce the pins; `download.sh` never runs them. The live NBIA
listing has 320 ReMIND US series: 114 `US_pre_imri`, 104 `US_pre_dura` and
102 `US_post_dura`. Only `US_pre_dura` is used, so the material stays one
surgical stage, before resection-cavity artefacts appear. The selection rule:
take each eligible patient's single series in ascending PatientID order, and
keep the longest prefix whose cumulative FileSize stays at or below
1,000,000,000 bytes. That prefix is 14 patients. Adding ReMIND-019 would
reach 1,044,876,310 bytes.

## Validation

`download.sh` checks the pin-file checksum and runs the parser self-test. It
re-validates every pin against the live listing: CC BY 4.0, ReMIND,
US_pre_dura, PixelMed converter, patient, study, ImageCount and FileSize. Each
object is fetched whole into a `.part` file, because NBIA ignores Range so
`curl -C -` cannot resume. The file must match the pinned size exactly. The
header is then walked, the regime asserted and the header SHA-256 compared,
and only then is the file renamed into place. `build.sh` re-validates and
emits the samples.

`verify.sh` locates Pixel Data independently from the end of the file, using
the pinned geometry, and cross-checks it against the header walker. It then
re-derives every sample, index row and statistic, and checks the manifest
totals and the 1 GB cap.

## License and safety

CC BY 4.0 (DataCite rightsList for 10.7937/3RAG-D070; NBIA LicenseURI on every
series). Cite: Juvekar et al. (2023), *The Brain Resection Multimodal Imaging
Database (ReMIND)*, The Cancer Imaging Archive,
https://doi.org/10.7937/3RAG-D070.

This is de-identified human clinical data: PatientIdentityRemoved YES,
BurnedInAnnotation NO, and pseudonymous IDs. Only voxel values are emitted.
Follow TCIA's data usage policy and do not attempt re-identification.
