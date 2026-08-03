# TCIA GammaPlan RTDOSE UInt16 Development — 2026-08-02

`tcia_gamma_plan_rtdose_u16` adds a new 16-bit domain: volumetric physical
radiotherapy dose plans. This differs materially from the accepted TCIA CT
family, which contains two-dimensional anatomical X-ray attenuation images.

## Discovery, source, and license

The TCIA modality query returned 524 bounded single-object RTDOSE series, all
with explicit CC BY 4.0 metadata. A cross-system probe selected three distinct
studies from each of two collections. The three Varian Eclipse abdominal grids
were native unsigned 32-bit and were excluded from this 16-bit recipe. All
three Elekta GammaPlan grids from `Vestibular-Schwannoma-SEG` were native
unsigned 16-bit.

The accepted source is TCIA collection DOI `10.7937/TCIA.9YTJ-5Q73`. Both the
live NBIA metadata and a `LICENSE` file included in every series archive state
CC BY 4.0. The collection consists of de-identified human medical data; this
recipe emits only dose-grid values, while TCIA's attribution and
non-re-identification conditions remain applicable.

## Representation and validation

Each source is one uncompressed DICOM RT Dose Storage object produced by
Elekta GammaPlan. The strict decoder requires physical planned dose in gray,
MONOCHROME2, one stored value per voxel, `BitsAllocated=16`, `BitsStored=16`,
`HighBit=15`, `PixelRepresentation=0`, and a finite positive
`DoseGridScaling`. It also requires the Pixel Data field to end the object and
to contain exactly `frames × rows × columns × 2` bytes.

The emitted samples are the complete Pixel Data fields copied byte-for-byte.
The per-volume scaling factors are retained in the index rather than applied,
so the compression target remains the source-native uint16 representation.

## Verified output

The accepted family contains three natural volumes from three distinct
studies:

- shape `153 × 181 × 148`, 4,098,564 values, scaling `0.000468040716`
- shape `153 × 187 × 144`, 4,119,984 values, scaling `0.000417146633`
- shape `154 × 184 × 151`, 4,278,736 values, scaling `0.00042602854`

In total it contains 12,497,284 values and 24,994,568 primary bytes. Each
volume spans stored values 0 through 65,535 and contains between 11,999 and
15,683 distinct values. All three sample sizes differ.

Build and verification passed. Verification reparses the pinned DICOM objects,
reapplies the full semantic and layout policy, checks the generated index and
statistics, and byte-compares every output volume against fresh source Pixel
Data.
