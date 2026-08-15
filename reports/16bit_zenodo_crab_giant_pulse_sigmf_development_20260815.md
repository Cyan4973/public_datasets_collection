# Crab Giant-Pulse SigMF Complex Int16 Development — 2026-08-15

## Outcome

Accepted `zenodo_crab_giant_pulse_sigmf_ci16`, one complete complex-baseband
radio-telescope recording containing a giant pulse from the Crab pulsar. The
capture was made with the Dwingeloo radio telescope on 2024-07-30 and released
as Zenodo record `10.5281/zenodo.13143544`.

This expands the native-16-bit corpus into radio astronomy transients. It uses
the same SigMF `ci16_le` representation class as the existing V16 NB-IoT
family, but its signal source and structure are different: a short,
wide-bandwidth astronomical event embedded in telescope receiver/background
noise rather than narrow-band cellular modem traffic.

## License resolution

Two source declarations differ:

- the Zenodo record metadata declares CC BY 4.0;
- the payload's embedded SigMF metadata declares CC BY-SA 4.0.

The accepted recipe conservatively applies the stricter embedded CC BY-SA 4.0
terms. The downloader independently requires both declarations and fails if
either changes. Attribution identifies Stichting CAMRAS, Maxwell Fine, and
Tammo Jan Dijkema.

## Native representation

The pinned SigMF metadata declares:

- datatype: `ci16_le`;
- sample rate: 20,000,000 complex samples/second;
- center frequency: 410,000,000 Hz;
- capture start: complex sample `0`; and
- capture time: `2024-07-30T09:19:20.197000Z`.

Every four source bytes are one complex sample: little-endian signed-int16 I
followed by little-endian signed-int16 Q. The complete `.sigmf-data` stream is
preserved byte-for-byte as one rank-two sample with shape `[4,000,000, 2]`.
There is no demodulation, filtering, scaling, byte swapping, truncation,
component splitting, or concatenation.

## Pinned source and realized output

The recipe pins the exact data/meta pair by filename, byte size, and Zenodo
MD5:

- `crab-giantpulse.sigmf-data`: 16,000,000 bytes,
  `a7a72584861a34ca76cb0813f6115749`;
- `crab-giantpulse.sigmf-meta`: 2,006 bytes,
  `e0e46f218f54a283eaaf04cbddf050da`.

Realized primary material:

- natural samples: 1;
- complex I/Q pairs: 4,000,000;
- scalar signed-int16 values: 8,000,000;
- primary bytes: 16,000,000;
- I range: `[-3,006, 2,990]`; and
- Q range: `[-3,357, 3,070]`.

The one-sample family is intentionally narrow but represents a complete,
materially large natural capture and comfortably passes both aggregate and
median-value floors.

## Verification

Build and verification passed. Verification reparses the SigMF metadata,
checks the embedded license and DOI, recomputes both source MD5 values,
validates the exact rate/frequency/capture geometry, scans all I and Q values
for nonconstant components and pinned ranges, and confirms that the emitted
little-endian sample is byte-identical to the source data stream.
