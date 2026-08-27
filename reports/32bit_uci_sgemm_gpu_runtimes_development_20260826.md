# UCI SGEMM GPU Runtime Float32 — 2026-08-26

## Outcome

Accepted `uci_sgemm_gpu_runtimes_f32`: four repeated GPU kernel execution-time
series over the same ordered sweep of 241,600 OpenCL SGEMM configurations.

The recipe contributes 966,400 float32 values and 3,865,600 primary bytes.
Each complete run is one fixed-size sample containing 241,600 values.

## New domain and shape

This family adds empirical computer-system performance measurements. Existing
numeric families include model weights, token streams, software metadata, and
physical sensor measurements, but no accepted family describes the performance
landscape of a hardware kernel across an exhaustive tuning-parameter sweep.

The four samples are repeated timing campaigns over an identical ordered set of
unique configurations. This preserves both systematic changes caused by kernel
parameters and run-to-run timing noise. The 14 discrete configuration columns
remain metadata rather than being widened into the float32 corpus.

## Source, rights, and representation

The exact official UCI ZIP is 3,186,088 bytes and is pinned by SHA-256. Its
single `sgemm_product.csv` member contains 241,600 unique configurations, 14
integer tuning columns, and four runtime columns. The official UCI metadata and
dataset page are also identity-pinned; the page grants CC BY 4.0.

The source stores runtimes as decimal CSV text rather than native binary words.
Each positive finite decimal is parsed and rounded once to IEEE-754 binary32,
then serialized in canonical little-endian order. This is explicitly classified
as a derived operational numeric representation.

## Verification

All four output samples are nonconstant and byte-distinct, with approximately
58,000 distinct binary32 values each. Verification checks the three source and
rights identities, ZIP member size/compressed size/CRC, exact CSV schema, row
and unique-configuration counts, expected output hashes, little-endian sample
metadata, absence of stale files, and every output byte against a fresh CSV
conversion.
