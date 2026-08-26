# High-Pressure Zeolite Powder-XRD Float32 — 2026-08-26

## Outcome

Accepted `zenodo_powder_xrd_patterns_f32`: 147 complete experimental powder
X-ray diffraction intensity curves from Zenodo record `4955141`, *Data from:
Pressure-induced symmetry changes in body-centred cubic zeolites*.

The recipe contributes 647,009 float32 values and 2,588,036 primary bytes.
Natural samples contain 4,396–4,405 values, with a median of 4,403.

## New domain and shape

This family adds one-dimensional materials-characterization spectra whose
structure consists of diffraction peaks, background, pressure-dependent peak
motion, and phase-transition behavior. It is distinct from the accepted
silicon EBSD family: EBSD stores a two-dimensional electron-backscatter
detector image, whereas this recipe stores one-dimensional X-ray scattering
intensity curves ordered by a measured angular coordinate.

The four experimental groups are balanced across two zeolite frameworks and
loading states:

- Na-X empty: 36 scans;
- Na-X filled: 38 scans;
- RHO empty: 34 scans; and
- RHO filled: 39 scans.

Each source `.xy` file is a natural pressure-step measurement and remains an
independent sample.

## Source and rights

The exact 36,220,726-byte archive is pinned by MD5
`7c674d184639b5d84a387af11930da6d`. The Zenodo record explicitly declares
`cc-zero` and identifies the study authors. It contains public experimental
materials data with no personal or participant content.

Broad discovery initially screened 400 Zenodo records and found many plausible
numeric tables. The accepted source was selected because it combines an
unambiguous CC0 grant, explicit high-pressure powder-XRD semantics, a coherent
single experiment, many naturally sized scans, and a small direct archive.
Unrelated thermogravimetric and generic tabular members found elsewhere are not
part of this recipe.

## Parsing and representation

Only archive members under the exact hierarchy
`Zeolite {Na-X,RHO}/{Empty_data,Filled_data}/*.xy` qualify. Every selected file
must decode as UTF-8, contain exactly two numeric columns after any leading
header, have a strictly increasing coordinate column, contain at least 1,000
rows, and have finite non-degenerate intensities.

The first column is validated as the scan-order coordinate but is not emitted.
The second decimal column is rounded once to IEEE-754 binary32 and written in
canonical little-endian order. The recipe therefore declares
`derived_operational_numeric`, rather than claiming that the ASCII source has a
native binary width.

The source contains one exact duplicate intensity payload:
`zFAUf_p19.xy` duplicates `zFAUf_p18.xy`. Deterministic lexicographic selection
keeps `p18` and excludes `p19`, leaving 147 unique samples.

## Verification

Build and independent verification passed against the pinned local archive.
Verification rechecks record identity and CC0 metadata, archive size and MD5,
ZIP safety and member inventory, strict source parsing, the exact duplicate
relationship, expected group counts, source-to-output byte equality, sample
hashes, little-endian float32 schemas, natural sample boundaries, and aggregate
acceptance limits.
