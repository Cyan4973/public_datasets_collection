# Neuropixels Opto Kilosort template float32 development — 2026-08-06

## Outcome

Accepted `zenodo_npx_opto_templates_f32`, 14 native-float32 Kilosort spike-
waveform template tensors from Zenodo record `18461445`, *Recordings with
prototype Neuropixels Opto probes in the mouse cerebral cortex*, DOI
`10.5281/zenodo.18461445`, released under CC BY 4.0.

## Domain and shape distinction

This is the corpus's first accepted neural-electrophysiology spike-template
family. It contributes sparse learned waveform tensors rather than raw
continuous voltage traces, images, simulation fields, event tables, or scalar
time series. Each complete session is a rank-three tensor with axes:

`spike template × 61 waveform time samples × retained probe channel`.

Template counts vary from 210 to 434 and retained channel counts vary from 104
to 161. The varied session geometry is preserved instead of padding or
splitting tensors.

## Source and acquisition

The exact Zenodo record contains seven large ZIP/ZIP64 session archives whose
combined size is about 34.6 GB. The recipe pins every parent archive by name,
size, and MD5, parses its remote central directory, requires the exact expected
`templates.npy` inventory, and range-extracts only the 14 selected Deflate
members. Their compressed member data totals 13,926,008 bytes.

For every member, the recipe validates central and local ZIP headers,
compression method, compressed and uncompressed sizes, CRC32, complete NPY
SHA256, and numeric-payload SHA256. It also requires an NPY v1.0, C-order,
little-endian `<f4` tensor with the pinned shape and a 128-byte header.

## Accepted material

- 14 complete session tensors
- 4,363 total spike templates
- 35,104,768 float32 values
- 140,419,072 numeric bytes
- 14 unique sample payloads
- 4,363 unique template payloads, with no duplicates within or across sessions
- global value range approximately -91.868 through 75.789
- 31,870,121 exact zeros, or 90.786% of all values
- at least 610 nonzero values and 670 transitions in every template
- sampled distinct-value count of at least 90,576 per session
- zlib-9 ratios approximately 0.086 through 0.123, median about 0.094

The pronounced sparsity is intrinsic to the stored Kilosort templates and
makes this a deliberately challenging sparse-floating-point compression shape;
it should not be treated as representative of raw electrophysiology voltage.
The builder removes only each NPY header and copies the complete numeric
payload byte-for-byte. Independent verification reparses every source and
compares every emitted sample against that payload.

## License and safety

The exact record declares CC BY 4.0. It documents prototype Neuropixels Opto
recordings from four laboratory mice, including three ChRmine-expressing
animals and one control. The emitted samples contain only derived numeric
waveform templates. Session identifiers remain in provenance metadata; no
human participant or personal data is present.
