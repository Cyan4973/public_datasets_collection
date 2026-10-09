# TCIA ReMIND intraoperative brain ultrasound uint8 development

## Outcome

Accepted `tcia_remind_intraop_brain_ultrasound_u8`: 14 complete reconstructed
3D B-mode brain ultrasound volumes from TCIA's *Brain Resection Multimodal
Imaging Database* (ReMIND), one per patient (ReMIND-001 to ReMIND-018), all
from the `US_pre_dura` stage. That sweep is acquired after craniotomy and before
dural opening, in the AMIGO suite at Brigham and Women's Hospital.

This is new content in a modality the corpus already has at 8 bits. The
existing family, `zenodo_hc18_fetal_head_ultrasound_u8`, is 2D fetal B-mode.
This recipe adds a new source, a new anatomy (intraoperative brain and tumour)
and 3D tracked-sweep volumes. The user approved it as the third
autocollect-era TCIA family.

## Source and rights

- Source: TCIA NBIA REST API v1, collection ReMIND (Version 1, released
  2023-09-26), DOI https://doi.org/10.7937/3RAG-D070
- Listing: `getSeries?Collection=ReMIND&Modality=US` has 320 series
  (114 `US_pre_imri`, 104 `US_pre_dura`, 102 `US_post_dura`)
- Payload: 14 pinned `getSingleImage` objects, 972,784,450 bytes total
  (34,506,990-101,376,600 each). The pin file (SHA-256
  `d976c3ba4dda69561eaea386e6eb160d5a28244f5631af3a8bbcdf78a5741fed`) fixes the
  size, the header length and header SHA-256, the shape and the spacing.
- License: CC BY 4.0. DataCite `rightsList` for the DOI gives
  'Creative Commons Attribution 4.0 International' (SPDX `cc-by-4.0`). All
  320 NBIA US rows carry LicenseURI
  `https://creativecommons.org/licenses/by/4.0/`, and `download.sh`
  re-checks this for each pin.
- Safety: de-identified clinical imaging (PatientIdentityRemoved YES,
  BurnedInAnnotation NO). These are reconstructions without screen overlays.
  Only voxels are emitted. The pin file holds TCIA pseudonymous IDs and UIDs
  for provenance only.

## Shape and conversion

Each natural record is one single-file PixelMed `NRRDToDicom` Multi-frame
Grayscale Byte Secondary Capture object in Explicit VR Little Endian. Its
schema is 8/8/7 bits, PixelRepresentation 0, MONOCHROME2, identity rescale and
lossless, with native OB Pixel Data as the final element. A stdlib header walker
asserts this regime. The recipe then copies the `frames*rows*columns` voxel
bytes in source order (frame, row, column) and drops only the even-length OB pad
byte, after checking that it is zero. There is no windowing, cropping, resampling
or remapping.

Selection: `US_pre_dura` only (one surgical stage), patients in ascending
PatientID order, and the longest prefix with cumulative FileSize at most
1,000,000,000. That prefix is 14 volumes. Adding ReMIND-019 would reach
1,044,876,310 bytes. The source offers 104 such volumes (7.99 GB), so the cap,
not the source, sets the sample count.

Zero voxels are the region of the reconstruction bounding box outside the
swept acquisition cone. They are kept as stored.

## Accepted output

- Primary samples: 14 (one per distinct patient)
- Primary values / bytes: 972,270,283
- Minimum sample: 34,486,837 values (ReMIND-015, 77x587x763)
- Median sample: 69,039,216 values
- Maximum sample: 101,324,574 values (ReMIND-001, 222x611x747)
- Value range: 0-255. All 256 values are present in every volume.
- Zero fraction: 0.471045-0.626390 per volume, 0.562875 aggregate
- All-zero (bounding-box end) frames: 0-14 per volume
- In-plane spacing 0.125 / 0.129 / 0.147 mm, slice spacing 0.47-0.50 mm
- Per-sample SHA-256 values are recorded in
  `index/tcia_remind_intraop_brain_ultrasound_u8/samples.jsonl`.

Breadth (driver zlsim, after the sampling fix in a16dfc2): verdict OK. The
nearest family is `mpc_landsat_c2_l1_mss_dn_u8` at distance 0.0522 (loss
-0.0033), followed by SEVIR VIL 0.0555, HC18 ultrasound 0.0576 and Cassini
sigma0 0.074. The candidate is compression-equivalent to Landsat MSS, HC18 and
BBBC007, so it is novel but near. The fill-warning list is empty.

## Judge checks

- `gate.py` PASS (14 samples, median 69,039,216 values, width 8). I
  reproduced the gate's constant check, which reads a 71,428-byte head window
  plus a mid-file window for files over 64 MiB. The flagged sample is
  **`us_pre_dura_05`**, not `us_pre_dura_01` as the README says. Frame 0's top
  rows are blank, and the mid offset lands on row 0 of frame 75, whose first
  nonzero row is 102. The volume itself has 256 values and zero fraction
  0.606. This is a sampling artifact.
- `verify.sh` re-run by the judge: PASS (the tail locator and header walker
  agree, samples are byte-equal, and index, stats and manifest totals match).
  `build.sh` uses local files only.
- Bytes: I examined all 14 volumes. Nonzero medians are 25-103, with smooth
  distributions and at most 0.15% at 255. Adjacent-frame mean |delta| is
  5.8-10.7 with only 5-25% equal voxels, so frames are not duplicated. I
  rendered middle and quarter frames and axial reslices of four volumes. They
  show real curvilinear-sector brain B-mode images with no text or overlays.
  The ~8M value-1 voxels in ReMIND-002 are dark anechoic tissue inside the
  cone, not a fill block. Zero-run analysis: 98.4-99.7% of zeros are row-edge
  runs or blank rows, and 0.3-1.6% are interior. The README's 98.7-99.7% and
  0.3-1.3% come from a slightly different frame subsample.
- Rights: I fetched the DataCite record myself (CC BY 4.0, SPDX
  `cc-by-4.0`). I checked LicenseName and LicenseURI on all 320 rows of the
  listing that was downloaded. The scripts contain no credentials.
- Novelty: `novelty.py` (URL plus terms ReMIND, intraoperative, ultrasound,
  brain, resection, AMIGO, US_pre_dura) finds no other ReMIND recipe and no
  downstream match. `--type ultrasound_image` lists only HC18 (u8) and rat fUS
  (f32). Seven TCIA NBIA recipes exist at 16/32 bits, none of them ultrasound.
- Selection: I recomputed the cumulative FileSize prefix from the listing:
  972,784,450 bytes for 14 volumes, and 1,044,876,310 bytes with the 15th.
