# NASA TESS Float32 Light Curves — 2026-08-26

## Outcome

Accepted `nasa_tess_lightcurves_f32`: 64 variable-length stellar photometry
time series from eight TESS targets observed across sectors 61–68.

The recipe contributes 1,015,204 native float32 values and 4,060,816 primary
bytes. Individual target-sector samples contain 13,040–18,854 retained values.

## New domain and shape

This family adds time-domain stellar brightness measurements. The accepted HYG
photometry data is a static cross-star catalogue, while existing astronomical
FITS families are image planes or cubes. Each TESS sample instead follows one
star through successive observing cadences, preserving transit, variability,
flare, systematic-correction, and measurement-noise structure.

The natural record is one complete public SPOC target-sector light curve. No
unrelated targets or sectors are concatenated.

## Source and rights

The exact 64 official MAST FITS products total 126,650,880 bytes and are pinned
individually by product URI, size, and SHA-256 in `selection.tsv`. MAST marked
all of them `PUBLIC` during discovery. Their primary headers identify TESS and
NASA/Ames and contain no contrary copyright notice.

The pinned official NASA media guidance states that NASA content generally is
not subject to copyright in the United States and documents attribution,
non-endorsement, logo, and identifiable-person constraints. The output consists
only of scientific stellar-flux measurements. The official MAST TESS mission
page is also captured and pinned as provenance evidence.

## Decoding and filtering

The standard-library decoder reads the declared fixed-width FITS binary-table
layout rather than relying on hardcoded offsets. It requires scalar `E`
(IEEE-754 binary32) `PDCSAP_FLUX` and scalar `J` (signed int32) `QUALITY`
columns.

Rows retain their original order. A value is kept only when `QUALITY == 0` and
`PDCSAP_FLUX` is finite. Of 1,247,392 source rows, the recipe excludes 224,940
nonzero-quality rows and 7,248 otherwise non-finite flux values. Each retained
four-byte source word is reversed from FITS big-endian to canonical
little-endian without numerical conversion.

## Verification

All 64 samples are nonconstant and byte-distinct. Verification checks every
source size and SHA-256, reparses every FITS table from the pinned sources,
reapplies the quality and finiteness rules, confirms the exact aggregate
counts, rejects stale outputs, and compares every generated sample byte with a
fresh extraction.
