# AOMIC-ID1000 FreeSurfer 6 Per-Vertex Cortical Thickness Float32

This recipe collects per-vertex cortical thickness maps from the FreeSurfer
derivatives of OpenNeuro dataset `ds003097` (AOMIC-ID1000, Amsterdam Open MRI
Collection). There is one map per hemisphere for 200 participants, which gives
400 samples.

Each sample is the `surf/lh.thickness` or `surf/rh.thickness` file of one
participant. It holds grey-matter thickness in millimetres at every vertex of
that hemisphere's white-surface triangle mesh, computed by FreeSurfer 6.0.1
`recon-all` from 3T T1-weighted MRI. The run was most likely inside fMRIPrep
1.4.1, the version declared in `derivatives/fmriprep`: `recon-all.done` shows
fMRIPrep-style per-hemisphere `autorecon3` calls writing to `/out/freesurfer`. FreeSurfer stores the values as big-endian float32. The recipe
copies them exactly and changes only the byte order.

## Source and license

- Bucket: `https://s3.amazonaws.com/openneuro.org`, prefix
  `ds003097/derivatives/freesurfer/`. This is anonymous public HTTPS. There are
  928 `sub-NNNN` directories plus the `fsaverage` and `fsaverage5` templates;
  the templates are skipped.
- License: `ds003097/dataset_description.json` declares `"License": "CC0"`
  (`DatasetDOI` 10.18112/openneuro.ds003097.v1.2.1). The dataset README says
  the dataset "contains both raw and preprocessed data (and other
  'derivatives')". The FreeSurfer directory carries no separate license.
  `derivatives/fmriprep/dataset_description.json` has only fMRIPrep's unfilled
  template text in its `License` field. This recipe does not use that file.
- `download.sh` fails unless `License == "CC0"` and `Name == "AOMIC-ID1000"`.
- Citation: Snoek et al. (2021), *The Amsterdam Open MRI Collection*,
  Scientific Data 8:85, together with the OpenNeuro DOI.
- Safety: this is a deidentified human-subject neuroimaging derivative. Following
  the `openneuro_ds000030_*` precedent, it is flagged
  `contains_sensitive_data = true`. The recipe downloads no participant tables,
  demographics, psychometrics, images or free text.

## Selection

`discover.sh` makes metadata requests only (S3 ListObjectsV2) and reproduces
`selection.tsv`:

1. List the delimiter prefixes under `derivatives/freesurfer/` and keep the
   928 `sub-NNNN` directories.
2. Sort the IDs and take 200 evenly spaced slots, `floor(i * 928 / 200)`.
   This spreads the selection over the whole cohort, from `sub-0001` to
   `sub-0924`.
3. A participant is eligible if both thickness files exist with single-part
   MD5 ETags, `scripts/recon-all.done` exists, `scripts/recon-all.error` is
   absent, and `scripts/build-stamp.txt` matches the pinned stamp
   `freesurfer-Linux-centos6_x86_64-stable-pub-v6.0.1-f53a55a`. If a slot
   fails, the script walks forward to the next unselected eligible
   participant. In the pinned run on 2026-10-05, all 200 slot participants
   were eligible and none were replaced.

`selection.tsv` pins 600 objects by key, byte size and MD5:

- 400 thickness maps, 227,687,388 bytes;
- 200 build stamps of 58 bytes each.

The full cohort is 928 x 2 maps, about 1.03 GB, which exceeds the 1 GB cap.
A bounded 200-participant subset of about 228 MB fits easily.

## Format and conversion

FreeSurfer "new curv" layout (big-endian):

| bytes | content |
|---|---|
| 0..2 | magic `FF FF FF` |
| 3..6 | int32 `nvertices` |
| 7..10 | int32 `nfaces` (must equal `2*nvertices - 4`, a closed genus-0 mesh) |
| 11..14 | int32 values per vertex (must be 1) |
| 15.. | `nvertices` float32 thickness values |

The file size must equal `15 + 4*nvertices`. The values are decoded and written
in source vertex order as little-endian float32, one `.bin` per hemisphere
file:

```
samples/<id>/aomic_cortical_thickness_f32/sub-NNNN_{lh,rh}_thickness_n<nvertices>.bin
```

Sample lengths follow each participant's own mesh: 108,686 to 191,104
vertices, median 140,810.5. Vertex order follows the surface tessellation, not
a regular grid. The recipe does no resampling to `fsaverage`.

## Value domain, as distributed

- **Zeros:** these are kept. They lie almost entirely on the non-cortical
  medial wall, where the white and pial surfaces coincide. In the probe of
  `sub-0001` lh, 6,067 of 131,504 vertices (4.6%) were zero, and 6,042 of
  those were outside `lh.cortex.label`.
- **5.0 clamp:** FreeSurfer clamps thickness at its default 5 mm maximum. Values
  of exactly 5.0 are kept (211 vertices in the same probe).
- Otherwise the values are continuous, with about 124k distinct float32 values
  per map in the probe.
- Fatal in download, build and verify: any NaN or infinity, any value outside
  [0, 5], a constant map, more than 15% zeros, more than 5% clamped values,
  or fewer than 25% distinct values.

Realized over the 400 built maps (build of 2026-10-05):

| per-map statistic | min | median | max |
|---|---|---|---|
| zero fraction | 3.33% | 4.27% | 5.42% |
| exactly-5.0 fraction | 0.01% | 0.11% | 0.54% |
| distinct float32 values / vertices | 93.7% | 94.9% | 95.8% |

- Every map spans exactly [0.0, 5.0].
- Pooled over all maps: 2,421,960 zeros (4.25%) and 66,144 clamped values
  (0.12%).

## Homogeneity

- One cohort and protocol (AOMIC-ID1000).
- One FreeSurfer build: every selected participant's build stamp is checked
  byte-for-byte in download and build.
- One quantity and unit (mm) and one file type.
- Left and right hemispheres are the same measurement on the same mesh type.

## Relation to other recipes and candidates

- `openneuro_ds003097_aomic_dti_tensor_f32` is a separate candidate from the
  same OpenNeuro dataset. It covers diffusion-tensor NIfTI volumes from
  `derivatives/dwipreproc/`: a different acquisition (diffusion MRI),
  pipeline (eddy/topup correction plus a weighted-least-squares tensor fit),
  file, and quantity (six tensor components per 2 mm voxel). This
  recipe reads only FreeSurfer surface outputs derived from the T1w scan. The
  two share no objects.
- `openneuro_ds000030_t1w_mri_f32` comes from a different OpenNeuro dataset
  (ds000030) and holds raw T1w voxel intensities on a 3D grid. This recipe
  holds a fitted morphometric scalar on a subject-specific surface mesh.

## Expected output

- 400 samples, 56,920,347 float32 values, 227,681,388 bytes.
- Download: 227,700,278 bytes, counting the 400 maps, 200 stamps and the
  dataset description.

## Run

```bash
bash staging/openneuro_ds003097_aomic_cortical_thickness_f32/download.sh
bash staging/openneuro_ds003097_aomic_cortical_thickness_f32/build.sh
bash staging/openneuro_ds003097_aomic_cortical_thickness_f32/verify.sh
```

`python3 scripts/fs_curv.py selftest` runs the synthetic round-trip and
rejection tests. `build.sh` and `verify.sh` run them first.
