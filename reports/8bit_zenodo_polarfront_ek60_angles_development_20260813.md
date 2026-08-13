# PolarFront EK60 split-beam angles int8 development — 2026-08-13

## Outcome

Accepted `zenodo_polarfront_ek60_angles_i8`, the two native signed-int8
split-beam angle-code fields stored beside the already accepted int16 power
field in Zenodo record `7473204`, *Split-beam echosounder data from
keel-mounted EK60 during PolarFront 2022-05 cruise*. The record is released
under CC0 and identified by DOI `10.5281/zenodo.7473204`.

## Distinction from the accepted power family

This recipe deliberately reuses the exact source recording but not the same
numeric material. `zenodo_polarfront_ek60_power_i16` emits logarithmic acoustic
echo-power words. This family deinterleaves the separate signed-byte alongship
and athwartship electrical angle codes measured by the split-beam transducer.
The two fields describe echo direction across the water-column range bins.

## Source and decoding

The exact 45,896,704-byte RAW recording is pinned by MD5
`944f3af1aea3a51cfa7ef7912dde10ba`. The downloader first reuses that validated
accepted-recipe cache through a hard link or reflink-capable copy. The strict
decoder validates all 33,849 Simrad datagrams:

- 1 `CON0` configuration identifying PolarFront0522, ER60, and the
  18/38/120-kHz transducers;
- 30,407 `NME0` navigation datagrams, validated by type and framing but
  excluded; and
- 3,441 `RAW0` mode-3 datagrams in 1,147 synchronized three-channel pings.

Each RAW0 datagram has 3,188 int16 power words followed by 3,188 signed-byte
angle pairs. The first byte of every pair is emitted to the alongship series
and the second to the athwartship series. Deinterleaving preserves every
signed-int8 bit pattern and range-bin order. One-byte values are endianness
invariant and are declared little-endian for corpus consistency.

## Accepted material

- alongship: 3,441 complete profiles, 10,969,908 values and bytes;
- athwartship: 3,441 complete profiles, 10,969,908 values and bytes;
- combined: 6,882 samples, 21,939,816 primary values and bytes;
- 3,188 values per natural ping/channel/component profile;
- 3,441 unique hashes in each component;
- observed signed range -128 through 127 in both components; and
- at least 255 distinct codes and at least 3,118 adjacent transitions in every
  profile.

These raw electrical angle codes are high-entropy. Zlib-9 produces 3,199 bytes
from every 3,188-byte profile, a ratio of approximately 1.00345. The family is
therefore useful as difficult real scientific int8 material, not as an example
of an easily compressible series.

## Verification, license, and safety

The accepted-path build produced all 6,882 samples. Verification independently
rescanned the pinned source, reconstructed both components, and required every
output to be byte-identical to that reconstruction. It also rejected stale or
extra sample files and checked the stored index, profile hashes, distributions,
timestamps, channel ordering, and aggregate statistics.

The source record declares CC0. Samples contain only instrument angle codes;
navigation text, vessel positions, configuration payloads, power words, and
container framing are excluded. No personal or sensitive data is present.
