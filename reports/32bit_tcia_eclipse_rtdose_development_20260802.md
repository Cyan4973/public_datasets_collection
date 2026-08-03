# TCIA Eclipse RTDOSE UInt32 Development — 2026-08-02

`tcia_eclipse_rtdose_u32` adds a new 32-bit representation and scientific
field: native integer volumetric physical radiotherapy dose plans. No prior
accepted 32-bit recipe represents treatment-dose grids.

## Source, license, and selection

The source is TCIA collection `Pancreatic-CT-CBCT-SEG`, DOI
`10.7937/TCIA.ESHQ-4D90`. Live NBIA metadata identifies the selected objects
as abdominal `Eclipse Doses` series from Varian ARIA. Both that metadata and a
`LICENSE` file included in every downloaded archive explicitly state CC BY
4.0. The data are de-identified human medical records; the recipe emits only
dose-grid values, and TCIA's attribution and non-re-identification conditions
remain applicable.

Three bounded single-object series from three distinct studies were selected.
They complement the uint16 GammaPlan family with a different planning system,
anatomical region, grid geometry, and native integer width.

## Native representation and validation

Each source is one uncompressed DICOM RT Dose Storage object. The strict
decoder requires abdominal Eclipse/ARIA metadata, physical planned dose in
gray, MONOCHROME2, one value per voxel, `BitsAllocated=32`, `BitsStored=32`,
`HighBit=31`, `PixelRepresentation=0`, and a finite positive
`DoseGridScaling`. Pixel Data must end the object and contain exactly
`frames × rows × columns × 4` bytes.

The complete Pixel Data fields are copied byte-for-byte. The per-volume
scaling factor is recorded but not applied, preserving the source-native
uint32 compression target.

## Verified output

The accepted family contains:

- shape `101 × 92 × 119`, 1,105,748 values, 268,542 distinct values
- shape `92 × 98 × 133`, 1,199,128 values, 318,304 distinct values
- shape `83 × 103 × 141`, 1,205,409 values, 341,943 distinct values

In total it contains 3,510,285 values and 14,041,140 primary bytes. Stored
values span zero to between 1,910,489 and 2,325,323. Zero fractions range from
28.7% to 37.5%, while flattened transition fractions range from 63.1% to
71.8%; the grids are structured but far from constant. All sample sizes differ.

Build and verification passed. Verification reparses the pinned DICOM objects,
reapplies the full semantic and layout policy, checks the generated index and
statistics, and byte-compares every output volume against fresh source Pixel
Data.
