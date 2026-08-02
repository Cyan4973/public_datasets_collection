# VACV Core Segmentation MRC UInt16 Development — 2026-08-02

`zenodo_vacv_core_segmentation_mrc_u16` adds the corpus's first native-16-bit
3D volume: a ground-truth segmentation of vaccinia-virus cores in a
cryo-electron tomography volume. It is intentionally a sparse binary-label
case, not an intensity image.

## Source, license, and native layout

Zenodo record `20262954`, *3D segmentation for VACV cores*, was published by
Jiasui Liu under CC BY 4.0 with DOI `10.5281/zenodo.20262954`. The selected
source is:

- `032_original_ground_truth.mrc`
- source bytes: `107,649,024`
- MD5: `a06b214d041398b9d0f0e8702dce8d7a`
- MRC shape: `464 × 464 × 250`
- MRC mode: `6` (unsigned 16-bit integer)
- byte order: little-endian
- extended header: none

The exact record JSON is retained and validated for record ID, title, and
license. The MRC header declares 53,824,000 voxels and the file ends exactly
after the expected payload.

## Low-cardinality assessment

The source genuinely stores uint16 words, but it uses only two labels:

- background `0`: `52,401,944` voxels
- foreground `255`: `1,422,056` voxels
- foreground fraction: `2.642048%`
- Shannon entropy: `0.176110` bits per voxel before spatial modeling

This is retained deliberately as a narrow-values-in-wide-slots compression
case with meaningful 3D spatial structure. It is not constant or merely empty:

- occupied slices: `132` of `250`
- constant empty slices: `118`
- unique slice payloads: `133`
- flattened value transitions: `75,846`
- median foreground voxels per slice: `3,232.5`
- maximum foreground voxels in one slice: `21,078`

## Accepted representation and verification

The complete 464×464×250 volume is one natural 3D sample. Build removes only
the 1,024-byte MRC container header and copies all voxel bytes unchanged. Empty
boundary slices are retained because they are part of the natural volume.

- primary samples: `1`
- primary values: `53,824,000`
- primary bytes: `107,648,000`
- payload SHA-256:
  `eb6c793dc31d784273e5f8953a21f4f3b947f33e59fef65c92b0da6f99131f8e`

Verification rechecks source size/MD5 and Zenodo identity/license metadata,
reparses and characterizes the complete MRC volume, hashes the source voxel
block independently, and confirms that it matches the emitted payload and
indexed SHA-256 exactly.
