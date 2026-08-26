# UCI Hydraulic-System Cycles Float32

This staged recipe targets the 100 Hz signals in UCI dataset 447,
*Condition monitoring of hydraulic systems*. The source is an industrial
electro-hydraulic test rig run through 2,205 repeated 60-second load cycles.

The selected source matrices are the six pressure channels (`PS1` through
`PS6`) and electrical motor power (`EPS1`). Each matrix has 2,205 rows and
6,000 samples per row. One complete sensor/cycle row is therefore one natural
sample: 6,000 little-endian IEEE-754 float32 values (24,000 bytes). Source
inspection found that 1,238 `PS4` rows are identical all-zero traces. Those
constant duplicates are excluded; all other rows are nonconstant and mutually
unique. The candidate therefore produces 14,197 samples, 85,182,000 values,
and 340,728,000 bytes.

The lower-rate flow, temperature, vibration, cooling, efficiency, and virtual
condition-label files are deliberately excluded. Their natural 60-second rows
contain only 600 or 60 values and do not meet the corpus median-sample target.
The condition labels are also categorical annotations rather than measured
numeric series.

UCI distributes the archive as whitespace-delimited decimal text. The recipe
parses every token as a finite number, rounds it once to IEEE-754 binary32, and
writes canonical little-endian words. It declares the result
`derived_operational_numeric`; it does not claim the text source had a native
binary width.

Run from the repository root:

```bash
bash staging/uci_hydraulic_system_cycles_f32/download.sh
bash staging/uci_hydraulic_system_cycles_f32/build.sh
bash staging/uci_hydraulic_system_cycles_f32/verify.sh
```

The download step also captures the official UCI API metadata and dataset page.
The API response establishes dataset identity and the official page must contain
explicit CC BY 4.0 evidence before the source is accepted. Network access occurs
only in `download.sh`; build and verification are entirely local.
