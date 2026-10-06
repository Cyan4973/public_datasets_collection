# AOMIC-ID1000 DTI Weighted-Least-Squares Diffusion-Tensor Fields Float32

Complete per-participant diffusion-tensor volumes from the Amsterdam Open MRI
Collection ID1000 study (OpenNeuro `ds003097`), emitted bit-exactly as raw
little-endian float32. One sample = one participant's published
`model-DTI_desc-WLS_diffmodel.nii.gz`: 112 x 112 x 60 voxels (2 mm isotropic)
x 6 tensor elements = 4,515,840 values (18,063,360 bytes).

## Material

- Cohort and protocol: AOMIC-ID1000, 928 healthy young adults, one Philips 3T
  scanner, three SE-DWI runs per participant (1 b0 + 32 directions each,
  b = 1000 s/mm^2, 2 mm isotropic, 112 x 112 x 60 matrix), concatenated to 99
  volumes before preprocessing.
- Pipeline (AOMIC paper, Scientific Data 8:85, "Diffusion MRI
  (pre)processing"): MRtrix3 `dwidenoise`, `mrdegibbs`, `dwipreproc` (FSL
  eddy/topup), `dwibiascorrect` (ANTs), `dwi2mask`, `dwigradcheck`, then
  "we fit a diffusion tensor model on the preprocessed diffusion-weighted data
  using weighted linear least squares (with 2 iterations) as implemented in
  `dwi2tensor`. From the estimated tensor image, a fractional anisotropy (FA)
  image was computed and a map with the first eigenvectors was extracted using
  `tensor2metric`."
- Quantity: the apparent diffusion tensor D in mm^2/s (scanner frame). This is
  a **published derived model product** (a fitted parameter field), not raw
  acquisition. It is the upstream's native float32 release; nothing is
  refit, rescaled or rounded locally. The FA/mask headers carry descrip
  `MRtrix version: 3.0_RC3_latest-77-g7774aec6`; the diffmodel header carries
  `6.0.1` (an FSL version string, so the file was last written by an FSL
  6.0.1 tool), but its values reproduce the MRtrix3 FA map to float precision.

## Tensor component order

The 4th (slowest) NIfTI axis holds the six unique elements in the MRtrix3
`dwi2tensor` order **Dxx, Dyy, Dzz, Dxy, Dxz, Dyz** (D11, D22, D33, D12, D13,
D23). No sidecar documents this, so it was established empirically on
sub-0001 with `scripts/probe_component_order.py`:

- FA recomputed from tensor invariants,
  `FA = sqrt(1.5 - 0.5 * tr(D)^2 / tr(D^2))`, matches the published FA map with
  max abs error 5.8e-8 over all 172,959 brain voxels for the MRtrix3 layout,
  versus 1.18 (FSL dtifit layout) and 1.00 (dipy lower-triangular layout).
- FA is invariant to permuting the off-diagonals, so their order was fixed
  against the published first-eigenvector map (EVECS): the tensor's principal
  eigenvector agrees with EVECS at mean |cos| 0.99984 for (Dxy, Dxz, Dyz) at
  volumes 3, 4, 5, versus 0.72 to 0.84 for the other five permutations.
- Diagonal volumes are positive in 99.98-99.99% of brain voxels; off-diagonal
  volumes are about half positive.

Every build and verify repeats the FA cross-check for every participant
(tolerance 1e-5), using the pinned FA maps that download.sh fetches for
validation only.

## Zeros

Voxels outside the published `dwi2mask` brain mask are exactly 0.0 in all six
elements. The full volume, zeros included, is the natural record and is kept
uncropped and unmasked. For sub-0001 the zero fraction is 0.7702 (3,478,086
of 4,515,840 values; 172,959 brain voxels, equal to the FA-nonzero and mask
counts). The build reports per-participant zero fractions and the aggregate
in `filtered/<id>/ingest_stats.json` and in each index row.

Realized over the 32 built participants: zero fraction 0.7676 overall
(0.7056 to 0.8076 per participant), 33,588,444 nonzero values, 144,779 to
221,568 brain voxels per participant. The FA cross-check max abs error is
5.96e-8 for every participant.

## Fit-failure outliers (kept)

A handful of voxels per participant, typically at the mask edge, carry
non-physical WLS estimates: 123 of 5,598,074 brain voxels (2.2e-5) have a
diagonal element with magnitude above 0.01 mm^2/s, and the extreme values reach
-953.1 / +424.8 (sub-0653) or about +/-3 (sub-0103, sub-0363, sub-0450). These
are the published values; they also reproduce the published FA, so they are
upstream fit artefacts, not decode errors. They are kept unclipped. Per
participant, the 99.9th percentile of |nonzero value| is a stable 3.2e-3 to
3.6e-3, and the median mean diffusivity is 7.7e-4 to 8.5e-4 mm^2/s.

## Selection and scope

`discover.sh` (metadata only) lists `ds003097/derivatives/dwipreproc/`
(16,663 objects, 925 participant directories, all 925 with both diffmodel and
FA) and picks 32 participants at evenly spaced sorted ranks
`floor((2i+1) * 925 / 64)`, i = 0..31: sub-0015, sub-0045, ..., sub-0914. It
confirms each pick's header with a 4 KiB gzip range read (no substitutions
were needed). The result is pinned in `selection.tsv` (key, bytes,
single-part ETag/MD5), and download.sh checks the file's sha256.

- Download: 64 objects, 146,432,131 bytes (125,611,861 tensor + 20,820,270
  FA) plus the 1,290-byte `dataset_description.json`.
- Output: 32 samples x 18,063,360 bytes = 578,027,520 bytes, 144,506,880
  float32 values (33,588,444 nonzero, 23.2%). The build-time aggregate
  sha256 over the per-sample sha256 list is
  `83262392cd8558c7cc187e3fd888e29b34ee5b0c1ce82992e611c6d3ba0a6264`.
- Header facts enforced on every file: sizeof_hdr 348 (little-endian), magic
  `n+1`, dim (4,112,112,60,6) [FA: (3,112,112,60)], datatype 16, bitpix 32,
  pixdim 2 mm, vox_offset 352, scl_slope 1 or 0 with scl_inter 0. pixdim[0] =
  -1 (qfac) is normal and ignored.

32 of 925 participants keeps the family well above downstream's ~100 MB
per-family sampling while staying far below the 1 GB cap. Raising
`TARGET_PARTICIPANTS` in discover.sh reproduces a larger evenly spaced pick,
but then selection.tsv and the pinned totals must be regenerated.

## License

`https://s3.amazonaws.com/openneuro.org/ds003097/dataset_description.json`:
`"Name": "AOMIC-ID1000"`, `"License": "CC0"`, `"DatasetDOI":
"10.18112/openneuro.ds003097.v1.2.1"`. The dataset README states it "contains
both raw and preprocessed data (and other "derivatives")"; the dwipreproc
derivatives have no separate license file. download.sh aborts unless
License == CC0. Cite the AOMIC paper as requested in `HowToAcknowledge`.

## Safety

Deidentified human-subject MRI derivative, flagged `contains_sensitive_data =
true` per the ds000030 precedent. Only fitted tensor voxel values at 2 mm are
kept. No participant tables, demographics, psychometrics, raw or preprocessed
DWI (`desc-preproc_dwi`, 269 MB per participant, is never touched), or
anatomical images are downloaded.

## Files

- `discover.sh`, `scripts/discover_selection.py`: listing-based selection
  (metadata only; writes to `$DATA_DIR/discovery/<id>/` or
  `DISCOVERY_OUT_DIR`).
- `selection.tsv`: pinned 64 objects.
- `download.sh`: liveness check, CC0 check, resumable curl fetch with size and
  MD5 validation, then `aomic_dti.py check-downloads` (full semantic
  validation including the FA cross-check).
- `build.sh`, `verify.sh` -> `scripts/aomic_dti.py build|verify`.
- `scripts/probe_component_order.py`: reproducible component-order probe
  (needs one participant's diffmodel, FA and EVECS fetched separately; not
  used by the pipeline).
