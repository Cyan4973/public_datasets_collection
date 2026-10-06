# AOMIC-ID1000 FreeSurfer cortical-thickness float32 development

## Outcome

Accepted `openneuro_ds003097_aomic_cortical_thickness_f32`. It holds per-vertex cortical grey-matter thickness maps from the FreeSurfer 6.0.1 `recon-all` derivatives of OpenNeuro ds003097 (AOMIC-ID1000). There is one map per hemisphere for 200 evenly spaced participants.

This is the corpus's first surface-mesh morphometric scalar field.
- The accepted `openneuro_ds000030_t1w_mri_f32` and `openneuro_ds000030_fmri_bold_i16` recipes are voxel intensities on 3D/4D grids from a different OpenNeuro dataset.
- The staging candidate `openneuro_ds003097_aomic_dti_tensor_f32` shares the AOMIC dataset but no objects. It uses DWI from `derivatives/dwipreproc`, which is a different acquisition, pipeline and quantity.

## Source and rights

- Source: public anonymous S3 bucket `https://s3.amazonaws.com/openneuro.org`, prefix `ds003097/derivatives/freesurfer/`. It holds 928 `sub-NNNN` directories plus the `fsaverage` and `fsaverage5` templates, which are skipped.
- Dataset version: DOI 10.18112/openneuro.ds003097.v1.2.1.
- License: CC0 1.0.
  - `ds003097/dataset_description.json` declares `"License": "CC0"` (sha256 `077aaf2ad49e2c2681ed30bc21b743294885d135d7ced167526dec1abed43a95`, pinned).
  - The dataset README says the dataset "contains both raw and preprocessed data (and other 'derivatives')".
  - The AOMIC Scientific Data paper (Snoek et al. 2021, PMC7979787) states that the release includes "the complete Freesurfer directories containing the full surface reconstruction per participant".
- Safety: this is a deidentified, GDPR-reviewed human MRI derivative with randomized subject IDs. It is flagged `contains_sensitive_data = true` and `contains_personal_data = false`, following the ds000030 precedent. No participant tables, demographics or images are fetched.

## Shape and conversion

- Natural record: one participant's complete `surf/lh.thickness` or `surf/rh.thickness` file, in FreeSurfer "new curv" format.
- Validation before decoding:
  - big-endian magic `FF FF FF`;
  - int32 nvertices;
  - nfaces = 2·nvertices − 4;
  - values per vertex = 1;
  - file size = 15 + 4·nvertices.
- Decoding: the nvertices big-endian float32 values are written unchanged, in source vertex order, as little-endian float32. There is no rescaling, masking or resampling to fsaverage.
- Values kept as distributed:
  - medial-wall zeros, 4.25% pooled;
  - FreeSurfer's 5 mm clamp, 0.12% pooled.
- Fatal checks: any non-finite value, any value outside [0, 5], or a degenerate map.
- Selection: sort the 928 participants and take `floor(i*928/200)` for i = 0..199. `discover.sh` enforces eligibility; all 200 slots were eligible and none were replaced.
  - `selection.tsv` pins 600 objects by key, size and MD5: 400 maps and 200 build stamps.
  - Every build stamp equals `freesurfer-Linux-centos6_x86_64-stable-pub-v6.0.1-f53a55a`.
- Homogeneity: per the paper, all ID1000 scans came from one Philips 3T "Intera" scanner configuration, processed by FreeSurfer v6.0.1 inside fMRIPrep 1.4.1.

## Accepted output

- Participants: 200, from sub-0001 to sub-0924.
- Primary samples: 400 (200 lh + 200 rh).
- Primary values: 56,920,347 float32.
- Primary bytes: 227,681,388.
- Minimum sample: 108,686 values.
- Median sample: 140,810.5 values.
- Maximum sample: 191,104 values.
- Download: 227,700,278 bytes (400 maps, 200 stamps, the dataset description).
- Value domain: every map spans exactly [0.0, 5.0].
- Pooled counts: 2,421,960 zeros (4.25%) and 66,144 values exactly 5.0 (0.12%).
- Per-map ranges:

| per-map statistic | range |
|---|---|
| zero fraction | 3.33–5.42% |
| clamp fraction | 0.01–0.54% |
| distinct values / vertices | 93.7–95.8% |

## Judge checks

- **Gate:** `gate.py` passed with no warnings: values=56920347, bytes=227681388, samples=400, median 140810.5, widths [32].
- **Verify:** I ran `verify.sh` myself; it exited 0. The synthetic selftest passed, then all 400 sources were independently re-decoded with struct and matched the samples byte-for-byte. Floors and exact scope passed.
- **Bytes:**
  - Decoded 10 samples with my own struct reader; each equals the big-endian source values exactly.
  - Across all 400 maps: per-map nonzero mean is 2.39–2.86 mm (median 2.58).
  - In the samples I inspected: SD about 0.65–0.73 mm, p5 about 1.34–1.57 mm, p95 about 3.50–3.91 mm.
  - No −0.0 values. Float32 exponents fall at 123–129, and all 256 low-byte values occur.
  - All 400 sha256 and 4 KB-prefix hashes are unique; the 400 maps have 395 distinct vertex counts.
  - zlib-9 ratio about 0.83, xz about 0.77–0.81.
- **Reproducibility:**
  - One fresh S3 delimiter listing returned 928 subjects, and the slot rule reproduces the pinned 200 participants exactly.
  - build.sh and verify.sh read only local files.
  - The download log shows 600/600 objects fetched and matched by size and MD5, and the license check passed.
- **Rights:**
  - Read the CC0 `dataset_description.json` and the dataset README.
  - Read the AOMIC paper's full text through Europe PMC; it confirms FreeSurfer directories are part of the release and gives the single-scanner fact.
  - The OpenNeuro FAQ was unreachable (proxy 403) and is not relied on.
  - No credentials appear in any script; the only "token" hits are S3 pagination tokens.
- **Novelty:** `novelty.py` (URL plus terms freesurfer, thickness, cortical, ds003097, AOMIC, curv, morphometr) found no FreeSurfer or surface-morphometry material locally, in the registry or downstream. The only related match is the sibling DTI staging candidate, which uses disjoint objects.
