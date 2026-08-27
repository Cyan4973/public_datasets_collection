# Zenodo Battery EIS Complex Float32 — staging

This candidate targets repeated electrochemical impedance spectroscopy (EIS)
measurements from batteries under cycling, ageing, temperature, or state-of-
charge variation.

The desired numerical structure is a history of complex frequency-response
sweeps: `[cycle, frequency, complex_component]`, where the final axis pairs
source `Z_real` and `Z_imag` values. This is different from scalar spectra and
ordinary time series because each frequency point is a complex transfer-
function measurement and successive sweeps trace electrochemical degradation.

The selected source is Zenodo record `17792537`, a CC BY 4.0 processed release
derived from the CC BY 4.0 LiBforSecUse V2 source at record `6418665`. It
contains 4,297 experiments from 26 commercial 18650 cells. The authors aligned
each impedance spectrum to 61 logarithmically spaced frequencies from
`10^-2` to `10^4` Hz using cubic splines.

Run from the repository root:

```bash
bash staging/zenodo_battery_eis_complex_f32/discover.sh
```

Results are written to
`.data/discovery/zenodo_battery_eis_complex_f32/candidates.tsv`.

Discovery selected Zenodo record `17792537`, a CC BY 4.0 author-processed
release derived from the LiBforSecUse battery life-cycle measurements. Its
single 8.1 MB text table documents 26 cells, 4,297 experiments, and aligned
61-frequency `Z_real`/`Z_imag` spectra. Download and preflight it with:

```bash
bash staging/zenodo_battery_eis_complex_f32/download.sh
```

The preflight validates the exact record/table identities, license statements,
schema, cell boundaries, experiment IDs, frequency pairing, missing values,
and prospective little-endian float32 conversion.

Build and independently verify the samples with:

```bash
bash staging/zenodo_battery_eis_complex_f32/build.sh
bash staging/zenodo_battery_eis_complex_f32/verify.sh
```

The pinned result contains 26 variable-length rank-3 samples shaped
`[experiment, frequency=61, complex_component=2]`. Each cell is one natural
ageing history, with source row order preserving its cycle/SOC experiment
sequence and the final axis ordered as `[Z_real, Z_imag]`. Samples range from
14,152 to 193,248 bytes and total 524,234 float32 values (2,096,936 bytes).

The author-processed table uses blank real/imaginary pairs where spline
alignment would require extrapolation. The recipe retains every rectangular
position and encodes the 1,354 blank component values as canonical
little-endian float32 quiet NaNs (`0x7fc00000`). Non-missing decimal values are
rounded once to binary32. All 26 output payloads are nonconstant and distinct.
