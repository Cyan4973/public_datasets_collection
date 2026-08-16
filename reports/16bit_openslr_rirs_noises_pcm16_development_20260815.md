# OpenSLR Measured Room Impulse Responses PCM16 — 2026-08-15

## Outcome

`openslr_rirs_noises_pcm16` adds a genuinely new measured-acoustics family.
It emits 3,810 complete microphone-channel impulse responses containing
66,979,516 native signed-int16 values and 133,959,032 bytes.

| Source collection | WAVs | Output channels | Output bytes |
|---|---:|---:|---:|
| AIR | 107 | 214 | 18,158,048 |
| REVERB-2014 | 36 | 288 | 9,216,000 |
| RWCP | 182 | 3,308 | 106,584,984 |
| **Total** | **325** | **3,810** | **133,959,032** |

All sources use 16 kHz integer PCM. Natural samples are complete individual
channels rather than arbitrary blocks; their lengths range from 1,667 to
159,792 values, with a median of 15,000.

## License and provenance

The official OpenSLR resource 28 page explicitly declares `License: Apache
2.0`, identifies the resource as a database of real and simulated room impulse
responses and noises, and states that its audio uses 16 kHz sampling and 16-bit
precision. It attributes the included measured responses to the Aachen Impulse
Response database (AIR), the 2014 REVERB challenge database, and the RWCP sound
scene database.

The official 1,311,166,223-byte archive is pinned at SHA-256
`3b50cfde915b3984738169b4beb341e9f6b8062ae4c2076146c5db71c2c05dc7`.

## Selection

The recipe retains every measured RIR member identified by the archive's AIR,
REVERB-2014 RIR, and RWCP RIR naming groups. It deliberately excludes:

- point-source and isotropic noise recordings;
- REVERB and RWCP files identified as noise; and
- all 60,000 simulated small-, medium-, and large-room responses.

This selection keeps the family focused on physical room measurements and
prevents a very large synthetic grid from dominating the training material.
The 325 selected WAV containers occupy 133,979,812 uncompressed bytes.

## Representation and boundaries

The accepted WAVs comprise 38 mono, 107 stereo, 36 eight-channel, 75
sixteen-channel, and 69 thirty-channel files. Both classic PCM and
WAVE_FORMAT_EXTENSIBLE with the PCM GUID occur. The parser validates RIFF and
chunk sizes, the PCM subformat, 16 stored and valid bits, byte rate, block
alignment, optional fact-frame counts, sample rate, channel layouts, and ZIP
CRCs.

Each interleaved WAV is deinterleaved into one complete response per channel.
Values are not resampled, normalized, truncated, mixed, requantized, or
concatenated. Output serialization explicitly canonicalizes every signed-int16
value to little-endian order, including on a hypothetical big-endian build
host.

## Verification

Build and verification both passed on 2026-08-15. Verification independently
re-read every output as little-endian signed int16 and enforced:

- exactly 325 source WAVs and 3,810 output channels;
- complete coverage of every channel from every selected WAV;
- 66,979,516 values and 133,959,032 bytes;
- exact per-family and source-channel-layout aggregates;
- matching per-sample sizes, shapes, extrema, and SHA-256 values; and
- no empty, constant, or byte-identical output samples.

The authoritative acceptance audit classifies the recipe as `ok`; the median
sample contains 15,000 values, comfortably above the 1,000-value floor.
