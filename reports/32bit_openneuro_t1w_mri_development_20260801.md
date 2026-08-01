# OpenNeuro ds000030 T1w MRI Float32 Development — 2026-08-01

`openneuro_ds000030_t1w_mri_f32` adds complete native-float32 3D
T1-weighted structural MRI volumes. This is a new accepted modality and sample
geometry: the corpus previously contained uint8 MRI-derived segmentation
labels and uint16 CT slices, but no MRI signal-intensity volumes.

## Source and license

The source is OpenNeuro `ds000030`, the UCLA Consortium for Neuropsychiatric
Phenomics LA5c Study, DOI `10.18112/openneuro.ds000030.v1.0.0`. Its public
`dataset_description.json` explicitly declares `License: CC0`.

Metadata discovery found 265 BIDS T1w objects. The recipe pins the first 20 by
public S3 key, byte size, and single-part ETag/MD5. The user-run float32
downloader reused the already validated files from the rejected int16-width
attempt, so reclassification required no second network transfer.

The recipe retains only deidentified T1w voxel arrays. It excludes participant
tables, diagnoses, demographics, task data, and free text. The manifest marks
the source as sensitive human biomedical material despite its public CC0
release and deidentification.

## Native representation and realized output

Every selected file is a little-endian, identity-scaled NIfTI-1 single-file
volume with:

- datatype code: `16` (`float32`)
- `bitpix`: `32`
- shape: `176 × 256 × 256`
- voxels per natural sample: `11,534,336`
- bytes per natural sample: `46,137,344`

The bounded selection realizes:

- primary samples: `20`
- primary values: `230,686,720`
- primary bytes: `922,746,880`
- compressed source bytes: `241,392,401`
- per-volume stored-value range: minimum `0`; maxima from `586` to `1,418`

Twenty volumes keep the decoded primary output safely below the protocol's
decimal 1 GB cap. The builder preserves complete 3D volume boundaries and
source voxel order; it performs no quantization or physical-value conversion.

Build and verification passed. Verification reparses every gzip/NIfTI source,
requires finite nonconstant float32 values and identity scaling, reconstructs
the canonical little-endian payload, and byte-compares all 922,746,880 output
bytes while independently checking shapes, ranges, counts, acceptance floors,
and the aggregate cap.
