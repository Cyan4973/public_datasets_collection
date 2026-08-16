# OpenNeuro ds000030 fMRI BOLD Int16 — 2026-08-15

## Outcome

`openneuro_ds000030_fmri_bold_i16` adds ten complete native signed-int16
four-dimensional BOLD functional-MRI runs. The outputs contain 257,499,136
stored voxel codes and 514,998,272 bytes.

This is materially different from the accepted ds000030 structural-MRI family:
the existing family comprises static 3D float32 anatomical T1w volumes, while
this one preserves time-varying 4D int16 functional acquisitions.

## License, provenance, and safety

The official BIDS `dataset_description.json` declares `License=CC0` and DOI
`10.18112/openneuro.ds000030.v1.0.0` for the UCLA Consortium for
Neuropsychiatric Phenomics LA5c Study.

The source is public deidentified human imaging and remains marked sensitive.
Only voxel arrays and technical subject/task/geometry labels are retained.
Participant tables, diagnoses, demographics, task events, and free text are
not acquired or emitted.

## Discovery and selection

Official S3 metadata exposed 2,004 public non-derivative BOLD objects from 272
subjects and eight tasks. Eighty task/subject-balanced bounded gzip-prefix
probes all declared:

- NIfTI-1 single-file rank 4;
- datatype 4 / bitpix 16 (signed int16);
- little-endian storage;
- identity scaling; and
- a 64×64×34 spatial grid.

The deterministic selection keeps ten different subjects and covers all eight
available tasks: BART, BHT, paired-associate encoding and retrieval, rest,
SCAP, stop-signal, and task-switching. It occupies 309,475,689 compressed bytes
and 514,998,272 decoded bytes.

Every source is pinned by S3 key, byte size, MD5/ETag, and SHA-256. Every
decoded voxel payload is independently pinned by SHA-256.

## Representation and natural boundaries

Each source declares 3×3×4 mm voxels and a two-second repetition time. Time
axes range from 79 to 291 frames. One complete BIDS BOLD run is one natural
sample; subjects, tasks, or time points are never concatenated.

The output copies each complete NIfTI voxel payload in source order. Because
all selected sources are already little-endian, output bytes are identical to
the stored payload bytes. No scaling, masking, normalization, spatial
reordering, resampling, truncation, or imputation occurs.

Stored values are nonnegative BOLD magnitude codes despite the signed NIfTI
datatype. Per-run maxima range from 1,702 to 2,452 and about 1.56% of values are
zero background. All runs are nonconstant and have distinct payload hashes.

## Verification

Build and verification both passed on 2026-08-15. The verifier freshly
revalidates compressed-source hashes, decompresses and reparses every NIfTI,
and byte-compares all outputs. It enforces exact geometry, scaling, source and
payload identities, subject/task coverage, aggregate sizes, nonconstant and
unique frames within each run, and unique complete-run payloads.
