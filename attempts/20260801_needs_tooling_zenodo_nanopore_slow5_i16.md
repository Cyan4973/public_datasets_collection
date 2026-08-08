# Accepted: Zenodo Nanopore BLOW5 Raw Signal Int16

- Date: 2026-08-01
- Candidate: `staging/zenodo_nanopore_slow5_i16`
- Domain: Oxford Nanopore direct-RNA electrical current traces
- Intended natural sample: one complete nanopore read's raw-signal array
- Intended width: native signed int16
- Status: accepted on 2026-08-08 as `datasets/zenodo_nanopore_slow5_i16`

## Resolution

The tooling blocker was resolved by pinning and conventionally building
official slow5tools v1.4.0 with HDF5 disabled. Its pinned zlib+SVB-ZD fixture
decoded successfully without package installation. The accepted recipe emits
15,670 complete source-order reads containing 449,967,586 values and
899,935,172 primary bytes, then independently verifies every emitted byte.

## Metadata discovery

A metadata-only Zenodo search examined 44 unique records and required explicit
CC0 or CC BY licensing. It found one bounded matching source:

- Zenodo record: `14676368`
- DOI: `10.5281/zenodo.14676368`
- title: *Nanopore RNA004 MinION SIRV synthetic raw signal data*
- license: CC BY 4.0
- file: `SIRV_from_MNXKXX240359.blow5`
- source bytes: `717,345,984`
- MD5: `fa088d06040ef3202a61b01f49b1d831`

The SIRV reference molecules are synthetic controls, but the signals are real
instrument measurements rather than simulated waveforms. A bounded 64 KiB
range probe found `@data_source real_device`, `@is_simulated 0`, MinION device
metadata, RNA004 chemistry, and a 4000 Hz sampling rate.

## Native type confirmation

The embedded schema explicitly declares:

`len_raw_signal` as `uint64_t` and `raw_signal` as `int16_t*`.

The file is BLOW5 v0.2.0. Its fixed header declares compression method code 1
for records and signal compression code 1. Under the BLOW5 v0.2 format these
map to zlib record compression and SVB-ZD signal compression. SVB-ZD combines
signal differencing/zigzag mapping with StreamVByte-style integer coding; it
cannot be decoded by the locally installed `zstd` executable.

## Former blocker

Neither `slow5tools`, slow5lib, nor a compatible Python BLOW5 decoder is
available locally. Downloading the 717 MB payload before a decoder exists
would not provide an actionable path to typed samples. The candidate is
therefore `needs_tooling`, not rejected: its license, domain, native width,
source size, and natural record boundary are all suitable.

A valid retry must provide one of:

1. a declared and reproducible `slow5tools`/slow5lib decoder path; or
2. a dependency-free BLOW5 v0.2 record and SVB-ZD implementation validated
   byte-for-byte against an independent reference decoder.

Because decompressed signals may exceed the corpus cap, extraction must stop
only between complete read records and keep aggregate primary output below
1 GB. It must not truncate or concatenate reads merely to meet size policy.

Evidence:

- `.data/logs/zenodo_nanopore_slow5_i16/discover.latest.log`
- `.data/logs/zenodo_nanopore_slow5_i16/probe_blow5.latest.log`
- `.data/discovery/zenodo_nanopore_slow5_i16/candidates.tsv`
- `.data/discovery/zenodo_nanopore_slow5_i16/SIRV_from_MNXKXX240359.blow5.header64k`
