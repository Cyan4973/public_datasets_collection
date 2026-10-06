# AOMIC-ID1000 DTI diffusion-tensor float32 development

## Outcome

Accepted `openneuro_ds003097_aomic_dti_tensor_f32` from OpenNeuro `ds003097`
(AOMIC-ID1000, snapshot DOI 10.18112/openneuro.ds003097.v1.2.1).

This is the corpus's first diffusion-MRI family. Each sample is one
participant's published apparent-diffusion tensor field: six tensor elements
per 2 mm voxel, in mm²/s, fitted by MRtrix3 `dwi2tensor` (weighted linear least
squares, 2 iterations). The existing MRI recipes (`openneuro_ds000030_t1w_mri_f32`
and `openneuro_ds000030_fmri_bold_i16`) store scalar intensities from a
different dataset. Novelty kind: new quantity within a known modality.

## Source and rights

- Source: the public anonymous S3 bucket `https://s3.amazonaws.com/openneuro.org`,
  prefix `ds003097/derivatives/dwipreproc/` (16,663 objects; 925 participant
  directories, all with `model-DTI_desc-WLS_diffmodel` and `_FA`).
- License: CC0. The dataset-level `dataset_description.json` has
  `"License": "CC0"`; the file is pinned at sha256
  `077aaf2ad49e2c2681ed30bc21b743294885d135d7ced167526dec1abed43a95`, and
  `download.sh` aborts if the license changes.
- Coverage: the dataset README says it "contains both raw and preprocessed
  data (and other \"derivatives\")". The AOMIC paper (Sci Data 8:85,
  PMC7979787) lists `_diffmodel` ("Estimated parameters from the diffusion
  tensor model") among the released DWI derivatives. `dwipreproc/` carries no
  separate license.
- Safety: deidentified, GDPR-reviewed human MRI derivative. The output is
  brain-masked 2 mm tensor values only, with no participant tables,
  demographics or raw DWI. Flags are `contains_sensitive_data = true` and
  `contains_personal_data = false`, following the ds000030 precedent.

## Shape and conversion

- Natural record: one participant's complete
  `sub-NNNN_model-DTI_desc-WLS_diffmodel.nii.gz`. Shape 112×112×60×6, float32,
  NIfTI order (i fastest, then j, k, component).
- Component order: MRtrix3 Dxx, Dyy, Dzz, Dxy, Dxz, Dyz.
  - The diagonal positions are confirmed for every participant at build and
    verify time. FA recomputed from the tensor invariants must match the
    published FA map within 1e-5.
  - The off-diagonal order was confirmed against the published eigenvector map
    on sub-0001: mean |cos| 0.99984, against 0.72–0.84 for the other
    permutations.
- Conversion:
  - Gunzip, then strict NIfTI-1 header checks: LE sizeof_hdr 348, magic `n+1`,
    dim, datatype 16, bitpix 32, 2 mm voxels, vox_offset 352, identity scaling.
  - Copy the 4,515,840 float32 payload values bit-exactly to one little-endian
    `.bin`.
  - No crop, mask, rescale or clip is applied.
- Kept as published:
  - The exact-zero background outside the brain mask.
  - Rare upstream WLS fit-failure voxels: 123 of 5,598,074 brain voxels have
    a diagonal element above 0.01 mm²/s in magnitude, with extremes
    −953.08 / +424.75 in sub-0653.
- Selection: 32 participants at evenly spaced sorted ranks
  `floor((2i+1)·925/64)`, sub-0015 … sub-0914. They are pinned in
  `selection.tsv` by key, size and MD5 (sha256
  `ee3ad04b06d0c6493be7d68a83addb13dfc210b1c0c7595f971cb646f1301a62`). FA maps
  are downloaded only for validation.

## Accepted output

- Download: 64 objects, 146,432,131 bytes (125,611,861 tensor + 20,820,270 FA),
  plus the 1,290 B dataset description.
- Primary samples: 32 (18,063,360 B each)
- Primary values: 144,506,880
- Primary bytes: 578,027,520
- Median sample: 4,515,840 values
- Nonzero values: 33,588,444
- Zero fraction: 0.767565 overall, 0.7056–0.8076 per participant
- Brain voxels: 144,779–221,568 per participant, 5,598,074 in total
- Median mean diffusivity per participant: 7.675e-4 to 8.496e-4 mm²/s
- Diagonal-positive fraction: at least 0.9993 in every participant
- FA cross-check max abs error: 5.96e-8
- Aggregate SHA-256 over the per-sample sha256 list:
  `83262392cd8558c7cc187e3fd888e29b34ee5b0c1ce82992e611c6d3ba0a6264`

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/openneuro_ds003097_aomic_dti_tensor_f32`
  passed with no warnings.
- **verify.sh:** I ran `bash staging/.../verify.sh` myself; it exited 0. All 32
  samples are bit-exact against re-decoded sources, statistics and FA are
  recomputed from the stored bytes, and manifest scope matches the index.
- **Live discovery:** I re-ran `discover_selection.py` against the live S3
  listing into `/tmp/autocollect`. It found 925 eligible participants with no
  substitutions, and its output `selection.tsv` is byte-identical to the pinned
  one.
- **Independent decode:** my own stdlib decoder on sub-0015, 0247, 0478 and
  0712 found:
  - sample bytes equal to the gunzipped file from offset 352;
  - in-brain diagonal medians about 8e-4 mm²/s and p99.9 about 3.5e-3 (CSF);
  - off-diagonals centred on 0 with p5/p95 about ±1.8e-4;
  - no partial-zero brain voxels;
  - about 99% distinct nonzero bit patterns and an 8.0-bit low-byte entropy,
    so these are not widened half-precision codes.
- **Index:** across all 32 rows, sha256 values and brain-voxel counts are all
  distinct.
- **Rights:** I read the local `dataset_description.json` (CC0, pinned hash)
  and the live dataset README (derivatives are included). The AOMIC paper
  full text from Europe PMC lists `_diffmodel` among the DWI derivatives,
  confirms the dwi2tensor WLS fit, and states that all of ID1000 was acquired
  on one scanner version (Intera).
- **Scripts:** no credentials anywhere (the only token is the S3 listing
  continuation token).
- **Novelty:** `novelty.py` (URL plus AOMIC, ds003097, diffusion tensor,
  diffusivity, dwipreproc, fractional anisotropy, diffusion MRI) finds no
  diffusion family locally, in the registry, the ledger or downstream. The
  only same-dataset hit is the sibling cortical-thickness candidate, which
  uses a different pipeline, file and quantity.
- **Open questions:**
  - The FSL "6.0.1" descrip on the tensor file does not matter, because the
    values reproduce the MRtrix FA to float precision.
  - 32 of 925 samples is a justified cap: 578 MB, more than 5× downstream
    sampling, with the 1 GB cap allowing only about 55.
