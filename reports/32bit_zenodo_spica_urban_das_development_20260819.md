# Spica Urban DAS MiniSEED Float32 — 2026-08-19

## Outcome

`zenodo_spica_urban_das_f32` adds nine synchronized day-long DAS waveform
traces containing 38,880,000 native float32 values and 155,520,000 decoded
bytes. Every natural sample contains 4,320,000 values: exactly 24 hours at
50 Hz.

The scientific domain overlaps the accepted conventional seismic waveform
family, so this is not claimed as a wholly new domain. It does add a distinct
sensing geometry and representation: multiple ordered virtual-station
positions measured along a distributed fiber, represented as native
floating-point waveform amplitudes rather than short conventional
seismometer windows in integer counts.

## Source and license

The source is Zenodo record 3549085, *Dataset used in “Urban Seismic Site
Characterization by Fiber-Optic Seismology” by Spica et al. in Journal of
Geophysical Research: Solid Earth*, DOI `10.5281/zenodo.3549085`. The exact
record declares CC BY 4.0 and names Zack J. Spica, Mathieu Perton, Eileen R.
Martin, Gregory C. Beroza, and Biondo Biondi as creators.

The recipe pins the sole `JGR_2019-master.zip` resource by its exact
92,177,152-byte size and deposited MD5. The archive contains nine selected DAS
traces at ordered virtual-station positions `055` through `095` in increments
of five. No unrelated archive content is emitted.

## Decoding and natural boundaries

Each `DS.20171008.NNN.mseed` member is one deposited channel/day stream and
therefore one natural sample. The dependency-free decoder traverses every
MiniSEED v2 record and blockette chain, requiring:

- one stable stream identity per member;
- blockette-1000 encoding 4, native IEEE float32;
- a valid declared word order and record length;
- 50 Hz sampling and finite values throughout;
- exact payload geometry with no truncated records; and
- timestamp-contiguous records over one common interval.

All nine streams begin at `2017-10-08T00:04:49Z`, end exactly 24 hours later,
and contain no gaps or overlaps. Source records declare big-endian words. The
decoder preserves every IEEE-754 bit pattern and reverses only each word's
byte order to produce canonical little-endian samples. It does not resample,
scale, quantize, fill, filter, or concatenate across channel boundaries. The
Zenodo deposit does not state the physical unit of its waveform amplitude, so
the recipe does not invent one.

## Verification

Build and verification passed on 2026-08-19. Verification reopens the pinned
archive, independently reparses and decodes every MiniSEED record, validates
source-member hashes and all timing/encoding metadata, and byte-compares each
complete output against a fresh reconstruction. It also requires the exact
nine output paths, float32 little-endian index schema, per-sample hashes,
38,880,000 values, 155,520,000 bytes, and the repository's aggregate and
median-sample acceptance floors.
