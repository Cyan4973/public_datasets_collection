# UCI EMG Data for Gestures Int8 — 2026-08-21

## Outcome

`uci_emg_gestures_i8` adds 568 complete surface-electromyography channel
timelines containing 33,265,144 signed-int8 values. The samples come from 71
complete Myo-armband gesture-session recordings across 36 participants and
eight electrode channels. Natural samples contain 44,927 to 77,878 values,
with a median of 57,841, comfortably clearing both acceptance floors.

This is a new physiological material and signal shape for the 8-bit corpus:
raw electrical skeletal-muscle activation with rest intervals and gesture
bursts. It differs from audio amplitude, image planes, packet fields, radio
strength, and categorical activity timelines already accepted at this width.

## Source and rights

The source is UCI dataset 481, *EMG Data for Gestures*, DOI
`10.24432/C5ZP5C`, created by N. Krilova, I. Kastalskiy, V. Kazantsev, V.A.
Makarov, and S. Lobov. The current official UCI page declares CC BY 4.0. The
recipe pins the official 17,699,840-byte archive, UCI API metadata, and UCI
rights page by exact size and SHA-256.

The recordings are public and deidentified but remain physiological signals.
The manifest conservatively marks them as personal and sensitive, excludes
participant codes from sample bytes, and prohibits identity, health, linkage,
or biometric inference.

## Exact representation recovery

The source text does not spell the channel codes as decimal integers. It
stores every reading as a decimal physical value on a `1e-5` lattice. An exact
decimal scan of all 33,903,256 channel tokens in the 72 nominal recordings
found that multiplication by `100000` always produces an integer in the full
signed-int8 range `-128..127`: there were zero off-lattice and zero
out-of-range tokens.

The recipe performs this exact inverse scaling with decimal arithmetic and
emits each recovered code as its two's-complement byte. It does not use
floating-point rounding, quantization, clipping, normalization, or imputation.
Each complete source recording/channel is one natural sample. Time and gesture
class are used only for structural validation.

## Malformed source recording

The archive contains 72 nominal recording tables. Subject 34's first session,
`1_raw_data_10-51_07.04.16.txt`, ends with a truncated final row containing
only nine fields: the gesture-class field is absent. The recipe rejects that
entire recording rather than silently deleting the row or fabricating a class.
The other 71 complete recordings are accepted. The archive README is also
recognized as a non-recording text member and rejected from the numeric scan.

## Verification

Build and verification passed on 2026-08-21. Verification reparses the pinned
archive using the same exact-decimal rules, reconstructs every natural
recording/channel timeline, checks the signed-int8 schema and output hashes,
byte-compares all 568 outputs with a fresh decode, and requires exact agreement
among source-derived profiles, index rows, ingest statistics, and sample files.
