# TEM tilt-series int16 development — 2026-08-04

## Outcome

Accepted `zenodo_tem_tilt_series_i16`, a bounded native signed-int16
transmission-electron-tomography projection sequence from Zenodo record
`3985424`, *Electron microscopy of SARS-CoV-2 particles - Dataset 05*, DOI
`10.5281/zenodo.3985424`, under CC BY 4.0.

## Domain and distinction

The existing `zenodo_vacv_core_segmentation_mrc_u16` family is a sparse binary
uint16 ground-truth label volume. This family instead contains dense signed
detector intensities from raw microscope projections across specimen angle.
The two recipes share an MRC container lineage but have different numeric
kinds, semantics, dimensional boundaries, value distributions, and generating
processes.

This source is conventional transmission electron tomography of ultrathin
plastic sections, not cryogenic electron tomography. The recipe deliberately
uses TEM terminology to preserve that distinction.

## Bounded source selection

The selected immutable source, `Dataset_05_SARS-CoV-2_009.mrc`, is a
1,048,708,096-byte uncompressed legacy FEI MRC mode-1 stack. Its 125 complete
2048x2048 projections contain 1,048,576,000 numeric bytes, slightly exceeding
the repository's 1,000,000,000-byte primary-output cap.

Because each projection is independently addressable, the recipe directly
range-fetches even acquisition indices `0,2,...,124`. This is a coherent
half-rate sequence of 63 complete natural frames spanning approximately -62 to
+62 degrees. It neither downloads the oversized object nor crops, splits, or
concatenates projection records.

The upstream object is pinned by size and MD5
`5cb0286e5a75ce2d330efa8c7e1440ae`; the exact header range is pinned by SHA-256
`50371751ebc9c6f011614b17ba577b1cce3db3480db13a0441fa36a6b4fb20c6`, and
the concatenated selected pixels by SHA-256
`931d9bd9099d92bc9a50e574023eab8f52bba0d4ac006494e151c4b38ee876cb`.

## Accepted material

- 63 fixed-size 2048x2048 signed-int16 projection samples
- 264,241,152 values and 528,482,304 numeric bytes
- 63 unique payload hashes
- tilt-angle coverage approximately -61.9994 through +61.9984 degrees
- at least 3,807 distinct values per frame
- global range -32768 through 32767 and no zero values
- zlib-9 ratios approximately 0.616 through 0.805, median 0.803

All values remain source-identical little-endian mode-1 words. The detector is
described as 12-bit, but the acquisition software natively represents the raw
image stacks in 16-bit storage; no rescaling or bit-depth conversion is used.

## Safety

The source consists of transmission-electron-microscopy images of extracellular
SARS-CoV-2 particles in laboratory Vero cell cultures. The recipe includes no
human-subject, patient, demographic, free-text, or identifying data.
