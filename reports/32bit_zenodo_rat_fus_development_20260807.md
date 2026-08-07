# Awake-rat functional-ultrasound float32 development — 2026-08-07

## Outcome

Accepted `zenodo_rat_fus_image_sequence_f32`, one complete native-float32
functional-ultrasound intensity tensor from Zenodo record `10074382`,
*Functional ultrasound imaging of stroke in awake rats*, DOI
`10.5281/zenodo.10074382`, released under CC BY 4.0.

## Origin of the candidate

The source was discovered while searching for native-int16 raw ultrasound RF
data. Range-only MATLAB directory inspection proved that the source is instead
processed functional-ultrasound imagery: its main `I` tensor is native
float32, while its small `t` and `t0` timing arrays are float64. The source was
therefore rejected at 16 bits and evaluated separately at its true width.

## Domain and shape distinction

This is the corpus's first accepted functional-ultrasound family. It records a
time sequence of ultrasound-derived image intensities from an awake rat rather
than raw RF receive channels, conventional audio, MRI/CT voxels, neutron
tomography, or acoustic geophysical traces.

The complete logical tensor has shape `187 image rows × 128 image columns ×
4500 time frames`. MATLAB column-major source order is preserved. The full
acquisition remains one natural rank-three sample rather than being split into
independently selected frames.

## Source and decoding

The exact 430,884,352-byte MATLAB v5 file is pinned by Zenodo size and MD5.
Its top-level matrix directory declares:

- array name `I`;
- `mxSINGLE_CLASS` and `miSINGLE` storage;
- little-endian byte order;
- shape `187 × 128 × 4500`;
- 107,712,000 values; and
- 430,848,000 numeric bytes beginning at exact MAT offset 192.

The downloader validates those fields and range-fetches only the numeric data
element. MATLAB framing and the float64 timing arrays are excluded.

## Accepted material

- 1 complete acquisition tensor
- 4,500 contiguous image frames
- 107,712,000 float32 values
- 430,848,000 numeric bytes
- all values finite and positive
- global range 276,883 through 12,316,307,456
- all 4,500 frame payloads unique
- at least 23,912 distinct values in every 23,936-value frame
- at least 23,934 spatial transitions per frame
- approximately 1,635,222 sampled distinct float bit patterns at stride 64
- zlib-9 ratio approximately 0.891

The almost continuous variation makes this a useful high-entropy floating-
point case, but it is not random or hash material: spatial layout, temporal
frames, instrument processing, and measurable lossless compressibility remain.

## License and safety

The exact Zenodo record declares CC BY 4.0 and names Clément Brunner as creator.
The selected file is explicitly an awake-rat pre-stroke session. Only numeric
image intensities are emitted; no human or personal data is present.
