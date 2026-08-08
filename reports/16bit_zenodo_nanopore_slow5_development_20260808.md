# Nanopore BLOW5 raw-signal int16 development — 2026-08-08

## Outcome

Accepted `zenodo_nanopore_slow5_i16`: 15,670 complete native signed-int16
electrical current traces from real-device Oxford Nanopore MinION RNA004
direct-RNA reads of synthetic SIRV controls.

## Domain and shape distinction

This adds a genuinely new numeric process: stochastic ionic-current sensor
traces produced while individual RNA molecules translocate through nanopores.
It is distinct from accepted extracellular neural voltage, RF I/Q, audio,
biomechanics, radar, and tabular genomics families. One natural sample is one
complete molecular read, so the family also contributes 15,670 independently
decodable variable-length one-dimensional shapes rather than a few long
channels or fixed-size matrices.

The reference material is synthetic SIRV RNA, but the record header explicitly
declares `data_source=real_device` and `is_simulated=0`; the electrical
signals are physical MinION measurements.

## Source and license

- Zenodo record 14676368
- DOI `10.5281/zenodo.14676368`
- title: *Nanopore RNA004 MinION SIRV synthetic raw signal data*
- creator: Hasindu Gamaarachchi
- license: CC BY 4.0
- payload: `SIRV_from_MNXKXX240359.blow5`
- payload bytes: 717,345,984
- MD5: `fa088d06040ef3202a61b01f49b1d831`
- SHA-256: `8d1e9caa3712780283fb66609268027e837992de0ba7e106a7a6061f72b34e4a`

The exact record title, creator, DOI, payload identity, and attribution are
retained. Synthetic controls contain no human or personal data.

## Decoder path

The former tooling blocker was resolved with a pinned official source build:

- slow5tools v1.4.0 commit `f73fc6b8f65813b7b1f5d787934d790e5d58b90f`
- slow5lib commit `e4bf785d696ce70eec4e54c37cbbdda19c25cc50`
- upstream-documented `make disable_hdf5=1`
- no package installation, Conda, HDF5, or build-time network fetches
- only compiler, GNU Make, zlib, and vendored StreamVByte

The preflight built in seconds and decoded the pinned upstream zlib+SVB-ZD
BLOW5 v0.2 fixture. The accepted helper links the same slow5lib statically and
uses its sequential record API; official `slow5tools quickcheck` separately
validates the whole source.

## Accepted material

- 15,670 complete source-order reads
- 449,967,586 signed-int16 values
- 899,935,172 primary bytes
- 4,596 to 586,693 values per read
- median 21,995 values per read
- full observed range -4,096 through 4,095
- 440,837,297 adjacent-value transitions
- 95 zero values
- every complete emitted sample has a unique SHA-256

Selection is the longest physical source-order prefix fitting below a fixed
900,000,000-byte cap. The next read has 37,604 values / 75,208 bytes and cannot
fit in the remaining 64,828 bytes. There is no content ranking, random choice,
or post-analysis cherry-picking.

## Identity and conversion

The embedded schema explicitly declares `raw_signal` as `int16_t*`. BLOW5
uses zlib record compression and SVB-ZD signal compression. Decoding restores
the native integer values; the recipe serializes them in canonical
little-endian order without current calibration, scaling, truncation, padding,
splitting, or concatenation.

Verification decodes the selected prefix again, matches every read ID, length,
range, zero count, transition count, and output byte, rejects extra or missing
files, reconstructs the index and summary, and proves the next record cannot
fit below the cap.
