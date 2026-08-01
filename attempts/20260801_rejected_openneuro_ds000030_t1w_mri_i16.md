# Rejected: OpenNeuro ds000030 T1w MRI Int16 — Source Is Float32

- Date: 2026-08-01
- Candidate: `staging/openneuro_ds000030_t1w_mri_i16`
- Intended domain: complete 3D T1-weighted structural brain MRI volumes
- Intended width: native signed-int16 NIfTI (`datatype=4`, `bitpix=16`)

## License and acquisition

Metadata discovery listed the fixed public `ds000030/` S3 prefix and selected
the first 24 BIDS `*_T1w.nii.gz` objects by key. The source
`dataset_description.json` explicitly declares `License: CC0` and DOI
`10.18112/openneuro.ds000030.v1.0.0`.

The user-run downloader completed successfully and validated all 24 exact
objects by tracked byte size and single-part S3 ETag/MD5:

- source files: `24`
- compressed source bytes: `289,115,515`
- source shape for every selected volume: `176 × 256 × 256`
- source endianness: little-endian
- NIfTI voxel offset: `352`
- NIfTI scaling: slope `0`, intercept `0` (identity by NIfTI convention)

## Rejection reason

Header inspection of every downloaded volume found:

- NIfTI datatype code: `16` (`float32`)
- `bitpix`: `32`

No selected volume uses datatype code `4` / `bitpix=16`. Emitting these files
as int16 would require lossy local quantization and would not be a native
16-bit series. Build and verification were therefore intentionally not run,
and the recipe was not promoted to `datasets/`.

The failure is a width mismatch, not a license, access, volume-boundary, or
material-quality problem. The exact material could be reconsidered as a
native float32 MRI family in a future 32-bit hunt. A 16-bit MRI attempt must
use a different source whose NIfTI or DICOM headers explicitly declare native
16-bit storage.

Evidence log:
`.data/logs/openneuro_ds000030_t1w_mri_i16/download.latest.log`.
