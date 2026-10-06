# Cyprus transmission-system PMU phase-voltage magnitude float32 development

## Outcome

Accepted `zenodo_gridgnosis_pmu_voltage_magnitude_f32` after one repair cycle.

This is the corpus's first synchrophasor family. It holds per-phase RMS voltage phasor magnitudes (phase-to-ground, about 77 kV on the 132 kV grid) reported at 50 frames per second by the phasor measurement units of the Cyprus transmission system.

It is distinct from the accepted `fingrid_nordic_grid_frequency_10hz_f32` (grid frequency) and from the downstream `power_voltage` family (1-minute household mains voltage).

The first review found one defect. Every GridGnosis PMU 6 export carries a phasor group labelled `_4_6` that is a copy of PMU 4's own `_4_6` group, so 1,606,515 values would have entered the corpus twice. The repair keeps only groups whose `<pmu>` id matches the file's PMU. The build fails closed unless each dropped column exactly matches its owner's column, and verify rejects any duplicated channel column.

## Source and rights

- Source 1: Zenodo record 20308780, "PMU data from the GridGnosis project" (Asprou, Avraamides, Stavrou, Demetriou; 2026-05-20). File: `Steady state data.zip`, 894,457,235 bytes, MD5 `24df9e74aa521ee21cf1fb03d42dceaa`.
- Source 2: Zenodo record 17648863, "PMU datasets from GridEye project" (KIOS CoE; 2025-11-19). File: `Steady state data.zip`, 201,941,844 bytes, MD5 `edf820db5b5d3dfd362df38c7cd32c8e`.
- License: CC BY 4.0. Both records' metadata declare `license: cc-by-4.0` with open access. download.sh re-checks the license, size and MD5 live before fetching.
- The event archives and line-parameter archives are a different regime and are never downloaded.
- `members.tsv` pins all 21 CSV members (name, compressed and uncompressed size, CRC32).

## Shape and conversion

Each natural record is one published one-hour steady-state PMU CSV export (about 180,000 rows of 20 ms frames).

**Sample layout.** A sample is a frame-major `frames × channels` little-endian float32 matrix holding the file's own `Mag_VA/VB/VC_<pmu>_<line>` columns, in CSV row order and header order. Channel counts per PMU:

| PMU | 1 | 2 | 3 | 4 | 5 | 6 | GridEye |
|---|---|---|---|---|---|---|---|
| Channels | 21 | 21 | 15 | 18 | 9 | 9 | 21 |

**Conversion.** Each token is parsed as a decimal and rounded to the nearest IEEE float32. The token must re-print identically from that float32, so the stored values reproduce the published numbers exactly. Angles, currents, Frequency and Dfrequency are not emitted.

**Missing values.**
- Zero-filled frames: kept and counted. None occur in the emitted samples.
- Zero-filled terminals: kept and counted. There are 879 values, all on terminal `1_13` right after a gap.
- Absent rows: not padded; each gap is recorded in the index. One 4,498-frame gap is shared by all six 2026-05-05 files.

**Exclusions.**
- `PMU_3_20260506_164000` is excluded because 164,718 of its 180,001 frames are zero-filled, over the pinned 50% rule.
- The foreign `_4_6` group in the three PMU 6 files is dropped and recorded per index row in `excluded_foreign_channels`.

## Accepted output

| Item | Value |
|---|---|
| Source members read | 21 (18 GridGnosis + 3 GridEye) |
| Members excluded | 1 |
| Primary samples | 20 (17 GridGnosis + 3 GridEye) |
| Primary values | 58,442,013 |
| Primary bytes | 233,768,052 |
| Minimum sample | 1,579,527 values (9 channels × 175,503 frames) |
| Median sample | 3,240,018 values |
| Maximum sample | 3,780,021 values (21 channels × 180,001 frames) |
| Frame counts | 14 samples × 180,001; 6 samples × 175,503 |
| Unique emitted channel columns | 327 |
| Stored value range | 61,980.84–79,641.52 V, plus 879 terminal zero-fill values |
| Download | 1,096,399,079 bytes |

## Judge checks

- **Gate:** `gate.py` printed PASS with no warnings (values 58,442,013; bytes 233,768,052; 20 samples; median 3,240,018; width 32).
- **verify.sh:** I ran it myself; exit 0 in about 4 minutes.
  - All 20 samples were re-derived by the independent parser and SHA-256 compared.
  - The excluded PMU 3 file was confirmed.
  - All 9 dropped foreign columns matched their owners.
  - `column_uniqueness_ok columns=327`.
  - build.sh and verify.sh contain no network calls.
- **Repair at the source:** I parsed 20,000 raw rows each of PMU_6 and PMU_4 for 2026-05-14.
  - The `_4_6` group is identical on every row and the timestamps match, while Frequency differs on 19,911 rows.
  - PMU 6's 9 own channels match the stored sample exactly (0 mismatches in 180,000 values).
  - PMU 6's own `6_4` terminal is genuinely different data (mean offsets of +1.1 kV and -10.6 kV).
- **Near-duplicates:** across all 327 columns, at most 0.15% of frames are exactly equal between any two same-window columns. Same-phase channels at one substation track each other within 1–1.7 V SD, as expected for line VTs on a shared bus.
- **Distributions:** means 76.8–78.6 kV, SD 34–155 V, 23k–42k distinct values per channel-hour, about 0.05% zero frame steps, zlib ratio 1.40–1.63.
- **Float32 origin:** 63,000 of 63,000 GridEye tokens lie within half a print unit of a float32 value, against 13.8% for random 3-decimal controls. The width is honest.
- **Zeros:** exactly 879, all in `Mag_V*_1_13` of `gridgnosis_pmu1_20260505`, frames 62206–62498. This matches the index.
- **Rights:** I fetched both Zenodo API records myself. Both report CC BY 4.0 with open access, and the file sizes and MD5s equal the pins.
- **Novelty:** `novelty.py` on both URLs (terms pmu, synchrophasor, phasor, gridgnosis, grideye, cyprus, kios) matched only this candidate. Labelled `new_source` because grid voltage exists downstream in a different form (household mains).
