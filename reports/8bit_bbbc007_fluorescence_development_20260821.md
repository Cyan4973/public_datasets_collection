# BBBC007 Microscopy Uint8 — 2026-08-21

## Outcome

`bbbc007_fluorescence_u8` adds 45 unique complete microscopy intensity planes
containing 8,050,720 native uint8 pixels from all 32 images in Broad Bioimage
Benchmark Collection image set BBBC007. Samples have 160,000 to 262,144
pixels, with a median of 160,000, comfortably clearing the aggregate and
median-sample acceptance floors.

This adds a new image-generation process to the 8-bit corpus: measured
fluorescence microscopy of Drosophila Kc167 cells stained for DNA and actin.
Existing microscopy coverage at this width consists of segmentation labels;
these samples instead preserve measured/rendered intensity morphology.

## Width-correct successor

The source was previously examined as `bbbc007_microscopy_tiff_u16` and
rejected because its TIFFs are 8-bit, not 16-bit. That result was not a source
or rights failure. The attempt registry now points to this native-width
successor so the prior investigation is not mistakenly repeated.

## Source and rights

BBBC007 version 1 contains Drosophila melanogaster Kc167 cell images acquired
with a motorized Zeiss Axioplan 2 and Axiocam MRm camera. The official page
states that the cells were stained for DNA and actin and that the two
biological channels are stored as separate 8-bit TIFF images.

The official page explicitly states that, to the extent possible under law,
Anne Carpenter has waived all copyright and related or neighboring rights to
the Drosophila Kc167 images and ground truth, and links the Creative Commons
CC0 1.0 waiver. The recipe pins both that page and the official 6,435,776-byte
image archive by exact size and SHA-256. The outlines archive is not needed and
is not downloaded.

## TIFF decoding and natural boundaries

The archive contains 32 TIFFs at 400×400, 450×450, or 512×512 pixels. The
physical files mix single-channel grayscale PackBits encoding and uncompressed
chunky RGB encoding even though all source samples are unsigned eight-bit.
A self-contained standard-library decoder validates byte order, one-image IFD
structure, dimensions, unsigned SampleFormat, BitsPerSample, photometric mode,
orientation, planar layout, strip geometry, and compression before decoding.

Each complete stored TIFF sample plane is one natural sample. Grayscale data
is emitted directly; RGB data is deinterleaved into its native red, green, and
blue planes. Eleven RGB planes are exact byte duplicates of another plane in
the same source image. The recipe deterministically retains the first copy,
yielding 45 unique planes instead of overweighting identical storage channels.
No pixel is rescaled, normalized, color-converted, quantized, filled, or
reordered.

## Verification

Build and verification passed on 2026-08-21. Verification reparses the pinned
archive independently, repeats the exact duplicate selection, checks uint8
schema and two-dimensional shapes, byte-compares all 45 outputs with the fresh
TIFF decode, and requires exact agreement among source-derived profiles, index
rows, ingest statistics, hashes, and sample-directory contents.
