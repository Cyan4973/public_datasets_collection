# Blocked: Zenodo ultrasound RF MATLAB int16 — 2026-08-07

## Intended family

`zenodo_ultrasound_rf_mat_i16` targeted native signed-int16 receive-channel
ADC tensors from permissively licensed Verasonics or comparable ultrasound
acquisitions. The desired natural geometry was time sample × receive element ×
transmit event/frame, restricted to phantom, simulated, or explicitly
non-human experiments.

## License and safety gates

Discovery admitted only CC0/CC BY records with explicit phantom, simulation,
in-vitro, ex-vivo, or non-human context. Human, patient, clinical, volunteer,
fetal, biopsy, and ambiguous-context records were rejected before payload
inspection.

## Bounded discovery

Seven targeted Zenodo queries returned 180 unique records. Twelve records were
both permissively licensed and passed the safety-context filter. Metadata,
remote ZIP directories, and 128-byte MATLAB headers identified 29 candidate
MAT files:

- 25 dependency-free little-endian MATLAB v5 candidates;
- four rejected MATLAB v7.3/HDF5 or undersized files; and
- 18,505,040,360 source bytes across the MATLAB v5 candidates.

All 25 MATLAB v5 candidates belonged to Zenodo record `10074382`, *Functional
ultrasound imaging of stroke in awake rats*, licensed CC BY 4.0. The files form
one consistently named/exported experimental family, with repeated sizes near
431 MB or 1.29 GB.

## Range-only dtype preflight

The representative baseline file
`Rat3_181205-AwakeStroke_PreStroke.mat` was inspected without downloading its
numeric payload. The exact 430,884,352-byte file is a little-endian MATLAB v5
file containing:

- `I`: native `miSINGLE` / `mxSINGLE_CLASS`, shape `187 × 128 × 4500`,
  107,712,000 float32 values and 430,848,000 numeric bytes;
- `t`: native float64, shape `4500 × 1`; and
- `t0`: native float64, shape `1 × 6`.

No top-level native int16 or uint16 array exists. The exact sizes and repeated
export pattern indicate processed functional-ultrasound image data rather than
raw Verasonics receive-channel ADC storage.

No large MAT payload was downloaded during discovery or dtype preflight.

## Outcome and retry condition

Blocked as a 16-bit source. Retry only with an exact permissively licensed
phantom or non-human MATLAB v5 file already known to contain an uncompressed
`miINT16`/`mxINT16_CLASS` or `miUINT16`/`mxUINT16_CLASS` RF/RcvData array.

The inspected `I` tensor is a substantial, directly range-addressable float32
candidate for a separate 32-bit functional-ultrasound family; it must not be
reinterpreted or quantized as int16.
