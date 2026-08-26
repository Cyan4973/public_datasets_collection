# UCI Hydraulic-System Cycles Float32 — 2026-08-26

## Outcome

Accepted `uci_hydraulic_system_cycles_f32`: 14,197 complete 60-second
pressure or electrical motor-power traces from UCI dataset 447, *Condition
monitoring of hydraulic systems*.

The recipe contributes 85,182,000 float32 values and 340,728,000 primary
bytes. Every retained natural sample contains exactly 6,000 measurements at
100 Hz.

## New domain and shape

This family adds repeated-cycle industrial electro-hydraulic telemetry. Its
signals capture pressure regulation, switching transients, load response, and
motor-power behavior while cooler, valve, pump, and accumulator conditions are
varied. It is distinct from existing image, scientific-spectrum, geophysical,
biomedical, and generic tabular float32 families.

The selected matrices are the six pressure channels `PS1` through `PS6` and
the electrical motor-power channel `EPS1`. Each matrix has 2,205 rows, one per
60-second operating cycle, and 6,000 columns, one per 100 Hz observation.
Keeping each sensor/cycle row independent preserves the source's natural
experimental boundary and yields many fixed-size samples.

The lower-rate flow, temperature, vibration, cooling, efficiency, and virtual
condition-label files are not emitted. Their natural rows contain only 600 or
60 observations, and the condition labels are categorical annotations rather
than process waveforms.

## Source and rights

The exact 76,601,704-byte official UCI archive is pinned by SHA-256
`24128aad2ee45eea7e6b63ebbd9992cdf25d0483a2cebefbfc13bc69079af1f2`.
The official API response pins dataset identity, title, DOI, creators, shape,
and sensor documentation. It contains no license field, so it is not used as
license evidence. The separately pinned official UCI dataset page explicitly
states that the dataset is licensed under CC BY 4.0.

The source contains laboratory machinery measurements and no personal or
sensitive data.

## Parsing and representation

Every selected member must occur exactly once and parse as precisely 2,205
nonblank whitespace-delimited rows of 6,000 finite decimal values. Each value
is rounded once to IEEE-754 binary32 and serialized in canonical little-endian
order. Because the source is decimal text without a declared native binary
width, the series is classified as `derived_operational_numeric`.

Source inspection found 1,238 `PS4` rows that are identical all-zero traces.
They are excluded as redundant constant samples. The remaining 14,197 samples
are all nonconstant and mutually unique after float32 conversion; no values
inside a retained cycle are removed or imputed.

## Verification

Build and independent verification passed against the pinned local archive.
Verification rechecks metadata identity and CC BY 4.0 evidence, exact resource
hashes, ZIP safety and member inventory, all matrix dimensions and numeric
tokens, the exact constant-cycle count, uniqueness of retained payloads,
source-to-output byte equality, little-endian float32 schemas, sample indexes,
and absence of stale or extra outputs.
