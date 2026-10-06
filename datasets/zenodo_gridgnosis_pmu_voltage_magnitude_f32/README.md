# Cyprus transmission-system PMU phase-voltage magnitudes (float32)

Synchrophasor material: per-phase voltage phasor magnitudes, in volts, reported
at 50 frames per second by the phasor measurement units (PMUs) of the Cyprus
transmission system. Each PMU monitors several 132 kV line terminals at one
substation. For each terminal it reports `Mag_V{A,B,C}`, the RMS
phase-to-ground voltage magnitudes, about 77 kV (132 kV / √3 = 76.2 kV).

One sample is one published one-hour steady-state CSV export. It is stored as
a frame-major `frames × channels` little-endian float32 matrix: one row per
20 ms frame, one column per voltage-magnitude channel, in CSV header order.
Only the file's own phasor groups are emitted, meaning groups whose `<pmu>` id
matches the file's PMU. Index rows record the channel names and counts,
because the channel count depends on the PMU (9 to 21).

## Sources and license

Both sources are Zenodo deposits whose record metadata declares
`license: cc-by-4.0`. `download.sh` re-checks the license live.

| Record | Title | File used | Size | MD5 |
|---|---|---|---|---|
| [20308780](https://doi.org/10.5281/zenodo.20308780) (2026-05-20) | PMU data from the GridGnosis project | `Steady state data.zip` | 894,457,235 | `24df9e74aa521ee21cf1fb03d42dceaa` |
| [17648863](https://doi.org/10.5281/zenodo.17648863) (2025-11-19) | PMU datasets from GridEye project | `Steady state data.zip` | 201,941,844 | `edf820db5b5d3dfd362df38c7cd32c8e` |

GridGnosis provides 18 CSVs: PMUs 1–6 × 3 windows (2026-05-05 14:53,
2026-05-06 16:40 and 2026-05-14 17:02, file-name local time). GridEye provides
3 CSVs from one PMU (morning, noon and evening of 2025-11-18). The GridEye
files use the identical export: the same `Date_Time, Mag/Angle_{V,I}{A,B,C}_<pmu>_<line>,
Frequency, Dfrequency` column pattern, 20 ms frames, the same 8-digit float32
prints and the same ~77 kV level. That is why they are part of this family.

The event archives (frequency and voltage events) and the line-parameter
archives are a different regime and are never downloaded. `members.tsv` pins
all 21 CSV member names, sizes and CRC32 values. `discover.sh` shows how they
were read from the ZIP central directories with a single range request.

## What is emitted

- Kept: every `Mag_VA/VB/VC_<pmu>_<line>` column whose `<pmu>` is the file's
  own PMU.
- Excluded: voltage angles, current magnitudes and angles, `Frequency` and
  `Dfrequency`.
- Each token is parsed as a decimal and rounded to the nearest IEEE float32.
  The CSV prints 8 significant digits, rounding exact decimal ties half away
  from zero. Every token must re-print identically from its float32, or the
  build fails. Both `build.sh` and `verify.sh` check every voltage token of
  all 21 files, about 62.7 M tokens including the excluded file, and none
  failed. The stored float32 values therefore reproduce the published numbers
  exactly.

Per-PMU emitted channel counts: PMU 1: 21, PMU 2: 21, PMU 3: 15, PMU 4: 18,
PMU 5: 9, PMU 6: 9, GridEye PMU: 21.

## Missing values, dropouts and exclusions

The exports show three kinds of missingness. Each one is handled explicitly,
and `verify.sh` re-checks each one independently.

1. **Zero-filled frames.** Every numeric field of the row (all magnitudes,
   angles, Frequency and Dfrequency) is exactly `0.0`. These frames are kept
   in place with their 0.0 voltages, the source's own sentinel, and counted in
   `dropout_frame_count`.
2. **Zero-filled terminals.** Inside an otherwise measured frame, one line
   terminal's whole 12-field phasor group is exactly 0. Its three 0.0 voltages
   are kept and counted in `terminal_zero_fill_voltage_values`. In the realized
   output this is 879 values: terminal `1_13` of PMU 1 for the 293 frames
   (5.86 s) right after the 2026-05-05 gap. Any other zero voltage is fatal.
3. **Absent frames.** Rows are missing from the export, which shows up as a
   timestamp step that is a whole multiple of 20 ms. They are not padded or
   interpolated, so the sample holds exactly the published rows. Each gap is
   recorded in the index (`gaps`: after which emitted frame, the resume
   timestamp, the number of absent frames). In the realized output, all six
   2026-05-05 files share one 89.98 s gap: 4,498 frames between 12:13:44.10
   and 12:15:14.08 (in-file timestamps). That gives 175,503 rows per file
   instead of 180,001. Because the gap is common to every PMU, it looks like a
   platform-side outage.

A file is excluded when zero-filled plus absent frames exceed 50% of its
20 ms lattice, because that hour was mostly not measured. This removes exactly
one file, `PMU_3_20260506_164000_20260506_174000.csv`. It is the one with the
suspicious 11:1 compression ratio: the PMU 3 stream stopped at 13:45:03 and
164,718 of its 180,001 frames are zero-filled.

The following are fatal in both `build.sh` and `verify.sh`:
- blank, non-numeric, NaN/inf or negative voltage tokens;
- ragged rows;
- repeated, backward or off-grid timestamps;
- headers that break the 12-column phasor group pattern;
- a channel whose measured mean falls outside 55–95 kV (a different nominal
  level), or a channel that is constant;
- any token that does not re-print from its float32.

## Homogeneity notes

All channels carry the same quantity, unit and nominal level, from the same
grid and the same frame rate. A few individual phases read persistently low:
`Mag_VA_2_18` ≈ 62 kV, `Mag_VB_4_24` ≈ 71 kV, and `Mag_VB/VC_6_4` ≈ 66.5 kV,
while their sibling phases read ≈ 77–78 kV. These look like per-phase
instrument-transformer offsets. They are kept as published.

**Foreign-PMU groups are dropped.** Every GridGnosis PMU 6 CSV also carries a
group labelled `_4_6`. In all three windows it is a bit-identical copy of
PMU 4's own `_4_6` group: all 12 phasor fields match on every row, while PMU
6's own Frequency column differs. Emitting it would put 9 channel-hours
(1,606,515 values) into the corpus twice. The build therefore emits only
groups whose `<pmu>` id equals the file's PMU.

The build fails closed: it stops unless every dropped foreign voltage column
is byte-identical to the owner PMU's same-named column in the same window
(float32 column SHA-256, same frames and timestamps). It records the dropped
names per index row in `excluded_foreign_channels`. `verify.sh` re-checks the
copy relation independently, asserts that every emitted channel carries its
sample's PMU id, and hashes every emitted channel column across all 20
samples, failing on any duplicate. No other duplicate column exists. GridEye
is unaffected, because all of its groups carry id 1.

## Realized scope

20 samples: 17 GridGnosis files (PMUs 1–6 × 3 windows, minus the excluded
PMU 3 file) plus 3 GridEye files. That is 58,442,013 float32 values and
233,768,052 bytes; the median sample holds 3,240,018 values. Fourteen samples
have 180,001 frames, one hour including both endpoints. The six 2026-05-05
samples have 175,503 frames. Sample sizes range from 1,579,527 values (PMU 5
and PMU 6, 9 channels) to 3,780,021 values (21 channels).

```bash
bash staging/zenodo_gridgnosis_pmu_voltage_magnitude_f32/download.sh   # ~1.10 GB
bash staging/zenodo_gridgnosis_pmu_voltage_magnitude_f32/build.sh
bash staging/zenodo_gridgnosis_pmu_voltage_magnitude_f32/verify.sh
```

`verify.sh` re-derives every sample with an independent parser (csv module,
strptime lattice, struct packing, an exact-Decimal re-print test). It
re-applies the missing-value, foreign-group and exclusion policies. It
byte-compares the samples, index fields, stored-float32 min/max and manifest
totals, and it rejects any duplicated channel column.
