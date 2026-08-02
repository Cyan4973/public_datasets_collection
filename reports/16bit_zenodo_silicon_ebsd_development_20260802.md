# Silicon EBSD Diffraction Pattern UInt16 Development — 2026-08-02

`zenodo_silicon_diffraction_tiff_u16` adds a new native-16-bit measurement
domain: a crystallographic electron backscatter diffraction detector pattern.

## Source, license, and modality

Zenodo record `1450892`, *Silicon Single Crystal Diffraction Pattern*, was
published by Ben Britton under CC BY 4.0 with DOI
`10.5281/zenodo.1450892`. The exact source is:

- `Si_pattern1.tif`
- source bytes: `3,715,496`
- MD5: `fb93782184b1b324eed85c1e377cc505`

The record identifies this as a single-crystal silicon pattern used in
AstroEBSD and provides pattern-center and orientation information for
crystallographic indexing. Although discovery began with broad X-ray/SAXS/WAXS
queries, the record metadata establishes that this exact image is EBSD rather
than an X-ray diffraction frame; the accepted recipe uses the accurate EBSD
description.

## TIFF layout and decoding

The first TIFF IFD declares:

- image shape: `1600 × 1152`
- samples per pixel: `1`
- bits per sample: `16`
- sample format: unsigned integer
- byte order: little-endian
- compression: PackBits (`32773`)
- strips: `64`, each nominally `18` rows
- orientation and planar configuration: `1`
- predictor: none (`1`)

Each strip is decoded independently with the TIFF PackBits rules and required
to produce exactly its declared number of rows. The 64 decoded strips are
concatenated in strip order to form one row-major detector plane. TIFF metadata
and compression framing are not emitted.

## Quality assessment and verified output

The complete decoded pattern contains:

- primary samples: `1`
- primary values: `1,843,200`
- primary bytes: `3,686,400`
- value range: `[4,093, 65,535]`
- distinct values: `3,659`
- zero values: `0`
- saturated values: `1`
- mean detector value: `25,882.840251`
- flattened transitions: `1,809,874`

The decoded output SHA-256 is
`7af126e2c7a6fdfddd680b66da75faebcb7585340b47ef3207b78411ad779f9c`.

Build and verification passed. Verification rechecks Zenodo identity/license
and source size/MD5, reparses the TIFF IFD and strip arrays, decodes every
PackBits strip independently, revalidates detector statistics, and byte-
compares the emitted detector plane with the independent decode.
