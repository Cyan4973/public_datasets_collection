# Honeybee Accelerometer PCM16 Development — 2026-08-02

`zenodo_accelerometer_pcm16` adds a new 16-bit measurement domain: physical
honeybee vibrations captured by an accelerometer.

## Source, license, and semantics

Zenodo record `7018660`, *Audio D18*, by Harriet Hall is released under CC BY
4.0 with DOI `10.5281/zenodo.7018660`. Its description explicitly states that
the WAV contains accelerometer data contributing to the honeybee mask in the
associated analysis. It further documents that the file concatenates 60
points for listening convenience and that each point is one second of
accelerometer data containing honeybee vibrations plus unavoidable background
noise.

The exact `D 18.wav` object is 5,760,044 bytes with MD5
`118ac1ee5a3ff3bc491b3103b06119b9`.

## Representation and segmentation

The source is a canonical RIFF/WAVE file with:

- integer PCM format `1`
- one channel
- 48,000 samples per second
- signed 16-bit little-endian words
- exactly 2,880,000 values / 60 seconds

The author describes this as a listening-oriented export, so the recipe does
not claim calibrated acceleration units or the original sensor ADC scale. It
does preserve every published PCM word exactly. The build removes only the
44-byte WAVE header and restores the documented boundary every 48,000 values,
yielding 60 fixed-size natural samples.

## Quality assessment and verified output

The accepted family contains:

- primary samples: `60`
- values per sample: `48,000`
- bytes per sample: `96,000`
- primary values: `2,880,000`
- primary bytes: `5,760,000`
- aggregate value range: `[-874, 873]`
- aggregate distinct values: `1,547`
- per-segment distinct values: `236` to `916`
- aggregate zero values: `108,606`
- aggregate transitions: `2,767,201`

Every segment is nonconstant and retains substantial local variation. The
complete PCM payload SHA-256 is
`8ddb9ca05969ce97469a88819854977e7e1e27f786c73dcda8345f7ee7adb775`.

Build and verification passed. Verification rechecks Zenodo metadata and
description semantics, source identity, RIFF/PCM structure, full payload hash
and statistics, all 60 segment hashes, and byte-compares each emitted sample
against a fresh split of the source data chunk.
