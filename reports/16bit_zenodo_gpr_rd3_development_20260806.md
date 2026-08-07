# Svalbard glacier GPR int16 development — 2026-08-06

## Outcome

Accepted `zenodo_gpr_rd3_i16`, 12 native signed-int16 ground-penetrating-radar
transects from Zenodo record `6856164`, *GPR snow depth survey over Svalbard
Glaciers*, DOI `10.5281/zenodo.6856164`, released under CC BY 4.0.

## Domain and shape distinction

This is the corpus's first accepted ground-penetrating-radar family. It records
subsurface snowpack reflections along glacier survey paths, unlike orbital or
weather radar images, RF communication IQ streams, sonar profiles, or
single-channel oscilloscope traces.

Each sample is one natural rank-two transect with axes `survey trace × 1,024
two-way-travel-time samples`. Trace counts vary from 1,357 to 29,602; no
padding, splitting, or cross-transect concatenation is performed.

## Source and decoding

The exact record contains four relevant ZIP archives totaling 123,434,133
bytes. Archive names, sizes, and MD5 checksums are pinned. Their 12 paired MALA
ProEx `.rd3` and `.rad` members are validated by exact inventory, ZIP geometry
and CRC, complete payload hashes, and header geometry.

Every RAD control file declares 1,024 samples, the exact matching trace count,
`SHORT FLAG:1`, an 800 MHz snow-survey antenna, and the same time window. The
RD3 byte sizes equal `trace count × 1,024 × 2` exactly. Little-endian decoding
is also strongly supported by local continuity: the focused profile's sampled
median adjacent step is 19 in little-endian order versus 4,608 byte-swapped.

## Accepted material

- 12 complete survey transects
- 98,628 total traces
- 100,995,072 signed-int16 values
- 201,990,144 numeric bytes
- all 12 profile payloads unique
- all 98,628 trace payloads unique within and across profiles
- no constant traces
- global value range -32,768 through 32,767
- 65,365 distinct values globally
- at least 269 distinct values and 931 transitions in every trace
- 42,752 zero values, about 0.0423% of the corpus
- zlib-9 ratios approximately 0.579 through 0.681, median about 0.593

Each complete RD3 payload is copied byte-for-byte. Independent verification
reparses the RAD geometry, recomputes source statistics and hashes, and checks
the emitted sample inventory against the original profile bytes.

## License and safety

The exact Zenodo record declares CC BY 4.0 and identifies five creators. It
describes unprocessed GPR snowpack surveys over five named Svalbard glaciers.
The recipe emits only radar amplitudes; source coordinate/position files,
markers, and text control metadata are excluded. No human or personal data is
present.
