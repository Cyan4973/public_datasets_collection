# TCIA Lung-PET-CT-Dx PET UInt16 Development — 2026-08-04

`tcia_lung_pet_ct_dx_u16` adds complete three-dimensional PET radiotracer
activity volumes. PET measures reconstructed positron-annihilation emission,
which is physically and statistically distinct from the corpus's anatomical
CT attenuation, T1-weighted MRI intensity, and planned radiotherapy dose
grids.

## Source discovery and license

The initially considered `FDG-PET-CT-Lesions` name is not exposed by TCIA's
live NBIA collection catalog. Discovery therefore moved to the live
`Lung-PET-CT-Dx` collection. Its API exposes 133 `PT` series from 133 distinct
studies; every returned series explicitly declares Creative Commons
Attribution 4.0 International.

The accepted bounded selection contains the three smallest `PET WB Corrected`
series from distinct studies: 136, 145, and 171 DICOM slices. Live metadata
pins their SeriesInstanceUIDs, StudyInstanceUIDs, image counts, descriptions,
license fields, and DICOM source byte totals. Every TCIA-generated archive also
contains an embedded CC BY 4.0 license file. The source contains deidentified
human medical imaging; the recipe emits only voxel arrays and technical
scaling metadata and retains no patient identifiers, diagnoses, demographics,
free text, or CT images. TCIA's prohibition on reidentification applies.

## Native representation

All 452 objects are uncompressed PET Image Storage DICOM using Explicit VR
Little Endian. Each slice is `200×200`, `MONOCHROME2`, one sample per voxel,
`BitsAllocated=16`, `BitsStored=16`, `HighBit=15`, and
`PixelRepresentation=0`. The declared activity units are `BQML`; decay,
normalization, attenuation, scatter, dead-time, and random corrections are
documented in the source metadata.

PET permits slice-specific `RescaleSlope` values. The first two selected
volumes contain 136 and 145 distinct slopes; the third uses one constant
slope. Build preserves the native stored uint16 values and retains every
ordered slice slope and intercept in the sample index rather than converting
to physical activity. Slices are ordered by unique `ImagePositionPatient`, and
their Pixel Data fields are concatenated without byte changes.

## Verified output

The accepted family contains three natural volumes:

- shape `136×200×200`: 5,440,000 values, range 0–65,535, zlib-9 ratio
  `0.292201`;
- shape `145×200×200`: 5,800,000 values, range 0–65,535, zlib-9 ratio
  `0.300733`; and
- shape `171×200×200`: 6,840,000 values, range 0–32,767, zlib-9 ratio
  `0.178269`.

Together they contain 18,080,000 values and 36,160,000 primary bytes. All
three natural sample sizes differ and all volumes have strong spatial
compressibility.

Build and verification pass. Verification reparses all 452 source objects,
rechecks license and DICOM semantics, reconstructs geometric slice order,
byte-compares every complete output volume against its ordered source Pixel
Data, validates per-slice scale arrays and hashes, and rejects missing or extra
outputs.
