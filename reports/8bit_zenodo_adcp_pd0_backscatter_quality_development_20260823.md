# Lower South San Francisco Bay ADCP Byte Fields — 2026-08-23

## Outcome

`zenodo_adcp_pd0_backscatter_quality_u8` adds three native byte-valued acoustic
Doppler current-profiler fields: correlation magnitude, echo intensity, and
percent good. Each family contains one complete time-by-depth-by-beam tensor
for each of three recordings, yielding nine samples and 43,130,088 uint8
values/bytes.

## Deliberate source reuse

The recipe reuses the exact three CC BY 4.0 recordings already owned and
pinned by `zenodo_adcp_pd0_i16`; it adds no independent cruises or source
files. The accepted int16 recipe extracts only earth-coordinate water
velocity. This recipe extracts the three unused native byte blocks, which
represent acoustic signal coherence, received echo strength, and solution
quality. It must therefore be counted as field and representation diversity,
not new observational coverage.

The shared cache avoids duplicating 82,736,476 downloaded bytes. Its owner
pins the Zenodo record identity, title, CC BY 4.0 license, and each source's
size and MD5.

## PD0 decoding

All 70,474 source ensembles have a fixed 1,174-byte record layout containing:

- correlation magnitude block `0x0200`;
- echo intensity block `0x0300`; and
- percent-good block `0x0400`.

Each block contains 204 native uint8 values arranged as 51 depth cells by four
beams. The decoder validates every ensemble header, length, offset table,
block ID, fixed-leader geometry, coordinate mode, and checksum before copying
the three byte fields. No values are scaled, reordered, dropped, or imputed.

## Quality and verification

Correlation samples contain 183–186 distinct values and echo-intensity samples
contain 182–191. Percent-good samples contain 46 values in the documented
0–100 range; zero is meaningful and occupies roughly two-thirds of those
fields rather than representing missing data. All samples have over one
million adjacent-value transitions except the smallest-recording correlation
and echo samples, which still exceed 1.68 million. No output is constant or
duplicated.

Build and fresh-source verification passed on 2026-08-23. Verification
rechecks record metadata, all source identities, all ensemble checksums and
layouts, the aggregate decoded SHA-256, output schemas and shapes, and exact
byte equality against a fresh decode. Each output has shape
`[measurement_ensemble, 51, 4]`; one-byte values are endian-independent and
recorded as little-endian for the corpus contract.
