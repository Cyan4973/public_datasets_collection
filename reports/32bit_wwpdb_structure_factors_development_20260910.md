# wwPDB X-ray structure-factor reflection fields float32

Date: 2026-09-10

Dataset ID: `wwpdb_structure_factors_f32`

Status: accepted

## Motivation

This family adds experimental single-crystal X-ray diffraction reflection
tables. Each sample is a scalar field over a sparse three-dimensional
reciprocal lattice, represented in source reflection-row order. This is
structurally distinct from the accepted wwPDB real-space atom-coordinate
series and from dense one-dimensional powder-XRD scans.

Amplitude and uncertainty remain separate homogeneous streams. Miller
indices are validated as structural coordinates but are not emitted: their
observed range is only 0 through 249 and therefore does not justify widening
them into a 32-bit family.

## Provenance and license

- Archive: Worldwide Protein Data Bank
- Selected entries: `1AON`, `1FFK`, `1J5E`, `2PTC`, and `4V9D`
- Source format: gzip-compressed PDBx/mmCIF structure-factor tables
- License: Creative Commons CC0 1.0 Universal
- Total compressed source size: 25,873,004 bytes

The exact five source objects are pinned in `selection.tsv` by URL, byte size,
MD5, and SHA-256. The RCSB search endpoint used during exploration returned
HTTP 400 and is deliberately excluded from the accepted recipe. Acquisition
uses only the five exact, independently validated file URLs.

## Decoding and representation

The recipe parses each reflection loop, validates its Miller `h`, `k`, and `l`
indices, and extracts `_refln.F_meas_au` and, when available,
`_refln.F_meas_sigma_au`. Source decimal values are rounded once to canonical
IEEE-754 float32 and serialized explicitly in little-endian byte order.

Explicit mmCIF missing tokens (`?` and `.`) are omitted independently from the
affected scalar field. Values from different physical columns are never
interleaved. Source row order and complete per-crystal field boundaries are
preserved.

## Accepted output

- Five measured-amplitude samples: 2,158,936 values, 8,635,744 bytes
- Four amplitude-uncertainty samples: 2,136,531 values, 8,546,124 bytes
- Total: 9 samples, 4,295,467 values, 17,181,868 bytes
- Sample lengths: 22,405 through 938,380 values
- Aggregate decoded-byte SHA-256:
  `16117e7501951c33722da0816b79e94f81c90d135e3bbf74ec082a9f4d03c5f8`

Build and verification independently enforce the pinned source identities,
reflection counts, field counts, missing-value counts, finite nonnegative
values, sample hashes, little-endian encoding, and aggregate output hash.
