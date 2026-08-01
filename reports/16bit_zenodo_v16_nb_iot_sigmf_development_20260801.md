# V16 Beacon NB-IoT SigMF Complex Int16 Development — 2026-08-01

`zenodo_v16_nb_iot_sigmf_ci16` adds a genuinely new native-16-bit domain:
software-defined-radio complex baseband recordings. The accepted material is a
coherent uplink/downlink pair from the same V16 automotive emergency-beacon
test, captured at the same instant and represented as raw SigMF `ci16_le`.

## Source, scope, and license

The two exact public Zenodo records are:

- `10.5281/zenodo.18202739`: NB-IoT uplink at 832.3 MHz
- `10.5281/zenodo.19771729`: NB-IoT downlink at 791.3 MHz

Both records explicitly declare CC BY 4.0 and identify Daniel Estévez as the
author. The downloader validates the live record-license metadata before
acquisition, then validates every data/meta file by exact byte size and Zenodo
MD5. Each SigMF metadata file additionally declares a SHA-512 digest for its
raw data file; those stronger hashes are also enforced.

An unrelated 16 MB Crab-pulsar telescope recording found during discovery was
excluded to keep the accepted recipe homogeneous.

## Native representation

Both SigMF metadata documents declare:

- datatype: `ci16_le`
- channels: `1`
- sample rate: `320,000` complex samples/second
- capture start: complex sample `0`
- capture datetime: `2025-12-31T11:44:19.5243983880865973Z`

Every four source bytes are one complex sample: little-endian signed-int16 I
followed by signed-int16 Q. The complete `.sigmf-data` file is the natural
record and is preserved byte-for-byte as a two-dimensional numeric sample with
shape `[complex_sample, component_iq]`. No demodulation, filtering, scaling,
channel splitting, truncation, or concatenation is performed.

## Realized output

- primary samples: `2`
- complex samples per recording: `109,706,068`
- scalar int16 values per recording: `219,412,136`
- bytes per recording: `438,824,272`
- total primary values: `438,824,272`
- total primary bytes: `877,648,544`
- median primary sample: `219,412,136` scalar values

Observed source-native component ranges confirm nonconstant, materially
different RF captures:

- uplink: I `[-26,091, 25,412]`, Q `[-26,191, 26,168]`
- downlink: I `[-1,665, 1,649]`, Q `[-1,817, 1,759]`

The decoded primary output remains 122,351,456 bytes below the decimal 1 GB
cap. Build and verification passed. Verification reparses all SigMF metadata,
recomputes source MD5 and SHA-512, scans every I and Q value for nonconstant
components and exact ranges, and confirms the generated sample SHA-512 values
match the pinned source recordings.
