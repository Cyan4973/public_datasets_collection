# Lower South San Francisco Bay ADCP Int16 Development — 2026-08-02

`zenodo_adcp_pd0_i16` adds a new native-16-bit measurement domain: acoustic
Doppler current-profiler velocity fields over time and water-column depth.

## Source and license

Zenodo record `5015459`, *Salinity and Velocity in Lower South San Francisco
Bay*, DOI `10.6078/D14H5K`, is released under CC BY 4.0. Metadata and bounded
PD0-header discovery selected three exact recordings totaling 82,736,476
source bytes. Every object is pinned by size and MD5.

## PD0 structure and decoding

All three files are exact concatenations of 1,174-byte records: 1,172 bytes
covered by the ensemble checksum followed by its two-byte checksum. Every
ensemble has the same six-block layout:

- fixed leader `0x0000`
- variable leader `0x0080`
- velocity `0x0100`
- correlation `0x0200`
- echo intensity `0x0300`
- percent good `0x0400`

The fixed leader declares four velocity components, 51 depth cells, 25 cm
cells, a 44 cm blanking distance, and coordinate-transform byte `0x1f`
(earth-coordinate mode). Each velocity block contains 204 native
little-endian signed-int16 words. The decoder validates every complete
ensemble and copies only these words, unchanged, into a recording-level field
with shape `[ensemble, depth_cell, velocity_component]`.

## Quality assessment and verified output

The accepted family contains:

- primary samples: `3`
- PD0 ensembles: `70,474`
- primary values: `14,376,696`
- primary bytes: `28,753,392`
- depth cells per ensemble: `51`
- velocity components per cell: `4`
- distinct values per recording: `2,831` to `3,462`
- valid observed range across recordings: `-9,197` to `9,537`
- retained invalid sentinel: `-32,768`
- invalid fraction per recording: `11.46%` to `12.12%`

The sentinel pattern is preserved because it describes cells without a valid
velocity solution and is part of the instrument's native field. Complete
recording samples retain temporal, depth, and cross-component structure; they
are not fragmented into tiny 204-value ensembles.

The concatenated decoded payload SHA-256 in manifest source order is
`98a4beb96fbd5e6ae46cca792019533d7857cbd60c26dc93faecd43bb114eb5c`.
Build and verification passed. Verification rechecks the Zenodo identity and
license, source hashes, all 70,474 ensemble checksums and layouts, decoded
hashes/statistics, and byte-compares all emitted recording fields with fresh
decodes.
