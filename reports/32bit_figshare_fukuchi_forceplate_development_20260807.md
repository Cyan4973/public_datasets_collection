# Fukuchi walking force-platform float32 development — 2026-08-07

## Outcome

Accepted `figshare_fukuchi_forceplate_c3d_f32`, the unique native-float32
force-platform analog matrices from the original C3D archive associated with
Figshare article `5722711` version 5, DOI
`10.6084/m9.figshare.5722711.v5`, under CC BY 4.0.

## Width correction and domain value

The source was first investigated as a 16-bit candidate. Forty representative
C3D headers all declared negative `POINT:SCALE`, which selects native float32
data records. The source was rejected at 16 bits rather than quantized, then
reevaluated at its true width.

This family adds walking kinetics rather than another motion-coordinate
family. Its analog matrices contain synchronized force and moment channels from
force platforms during overground and treadmill trials. The accepted Xsens
C3D family instead contains integer anatomical-landmark coordinates and no
analog channels.

## Source selection

The exact 732,874,413-byte `WBDSc3d.zip` archive is pinned by Figshare metadata
and MD5 `5d93531eab7acc8ebe786145cd26eea8`. It contains 2,019 C3D members totaling
1,120,525,352 bytes uncompressed.

The similarly sized `WBDSc3dWithGaitEvents.zip` archive is deliberately
excluded because it repeats the same trials with added event metadata. ASCII
exports, participant spreadsheets and anthropometrics, model files, and
processing scripts are also excluded.

## Accepted material

- 1,966 unique complete walking trials from 42 subject codes
- 1,638 overground and 328 treadmill trials
- 83,857,942 native float32 values
- 335,431,768 numeric bytes
- sample sizes from 36,584 through 432,000 bytes; median 120,768 bytes
- 12 or 34 analog channels from two or five force platforms
- 100 or 300 Hz analog sampling, with one or two analog subsamples per point frame
- source channel labels for force and moment components
- 637,877 zero values (`0.7606638%`)
- all values finite, global stored range about `-4.805` through `3.646`
- all 1,966 retained payloads unique
- median zlib-9 ratio approximately `0.398`

Fifty static calibration members are excluded by trial semantics. Three later
archive-order walking members have analog payloads exactly duplicating earlier
members and are excluded deterministically.

## Representation caveat

The output preserves the C3D-stored float32 analog words byte-for-byte. C3D
channel metadata labels the streams as force and moment quantities and records
units, scale, offset, and force-platform configuration. Physical calibration
may require those metadata; the stored range therefore must not be presented
as already calibrated newtons or N·mm. No rescaling is performed.

## License and safety

The Figshare article explicitly declares CC BY 4.0. The source contains
de-identified subject-coded walking recordings from 42 healthy volunteers,
including young and older adults. Movement dynamics can have biometric
character. The recipe marks the material as personal data, excludes names,
anthropometrics, and coordinate trajectories, and prohibits identification,
linkage, health inference, or biometric profiling.
