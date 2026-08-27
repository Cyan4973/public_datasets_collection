# Superseded: MorphoDunes PIV Float32

- Candidate ID: `zenodo_morphodunes_piv_f32`
- Source: Zenodo record `16414450`
- Decision: superseded by `zenodo_morphodunes_piv_f64`
- License: CC BY 4.0

All four downloaded MATLAB v5 files contain `uPIV`, `vPIV`, `xPIV`, `yPIV`,
and `zPIV` as native `mxDOUBLE` matrices backed by little-endian `miDOUBLE`
payloads. None is stored as float32.

The paired velocity fields are scientifically useful and structurally novel,
but converting them to float32 would unnecessarily discard source precision.
They were therefore accepted at their native width as
`zenodo_morphodunes_piv_f64`.

Do not retry this exact record as a 32-bit source. Other PIV records remain
eligible if file-level inspection proves native float32 storage.
