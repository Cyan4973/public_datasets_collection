# GRACE-FO calibrated platform-magnetometer B_NEC, float64

Complete daily 1 Hz geomagnetic field vectors measured in orbit by the AOCS
fluxgate magnetometers of GRACE-FO 1 and GRACE-FO 2. Values come from the GFZ
product *GRACE-FO calibrated and characterized magnetometer data*, version 0201,
category `ACAL_CORR`. In that product `B_NEC` is aligned and vector-calibrated.
GFZ publishes the satellite-disturbance corrections next to it as seven
separate `dB_*` terms. Those terms are nonzero in 47 of the selected files and
exactly 0.0 in the 17 files dated 2022-11-21..2024-11-10; see
[Disturbance-correction era](#disturbance-correction-era).
The recipe emits only the CDF variable `B_NEC` (nT, North-East-Centre frame),
one native float64 `[records, 3]` array per selected satellite-day
(86,400 records, or 86,399 where upstream omits one epoch).

- Source: <https://isdc-data.gfz.de/grace-fo/MAGNETIC_FIELD/0201/>
- DOI: <https://doi.org/10.5880/GFZ.2.3.2021.002> (Michaelis, Stolle, Rother 2021)
- License: CC BY 4.0. It is stated three times: the ISDC `README.txt` ("License:
  CC BY 4.0"), the DOI landing page (schema.org/DC rights `CC-BY-4.0`), and the
  global `License` attribute inside every CDF. The `Rules_of_use` attribute is
  only an as-is warranty disclaimer.

## Material

| item | value |
| --- | --- |
| series | `gracefo_fgm_acal_corr_b_nec_f64` (primary, only series) |
| sample | one file `GFn_YYYYMMDD_B_NEC.f64le.bin`, 86,400 × 3 float64 = 2,073,600 bytes (4 samples: 86,399 × 3) |
| layout | row-major; per 1 s epoch the interleaved triple (B_N, B_E, B_C), labels `Bnorth Beast Bcentre` |
| samples | 64 (34 GF1, 30 GF2), 2018-06-15 .. 2026-08-02 |
| primary total | 16,588,788 values, 132,710,304 bytes |
| disturbance terms | 47 samples nonzero (RMS 12.3–74.0 nT), 17 samples all exactly 0.0; index fields `disturbance_terms_zero`, `disturbance_total_rms_nT` |
| download | 64 CDFs, 975,321,560 bytes (8.3–18.5 MB each) + two 2.8 KB READMEs |

The values are full-precision binary64. In every realized sample each of the
three components has all-distinct values (distinct count = record count). None
of the 16,588,788 stored values is exactly representable in float32. Build
enforces both properties, verify re-checks them through an independent bit
test, and the index records them (`component_distinct_counts`,
`float32_exact_values`). Across all 64 samples values span -52,823..49,185 nT and
|B| spans 18,281..52,920 nT. The series is dominated by the main field swinging
along ~15 polar orbits per day, with superposed crustal, ionospheric and
magnetospheric signals and residual platform noise.

## Disturbance-correction era

Each ACAL_CORR file carries seven satellite-disturbance terms next to `B_NEC`:

| variable | disturbance source |
| --- | --- |
| `dB_MTQ_FGM` | magnetorquers |
| `dB_XI_FGM`, `dB_NY_FGM` | 2nd/3rd-order non-linearities |
| `dB_BT_FGM` | temperature dependency of offsets |
| `dB_ST_FGM` | temperature dependency of scale factors |
| `dB_SA_FGM` | solar-array currents |
| `dB_BAT_FGM` | battery currents |

All are CDF_DOUBLE[3] in the FGM frame, in nT.

- **47 samples** (2018-06-15..2022-10-07 and 2025-03-25..2026-08-02): all seven
  terms are nonzero. The RMS over records and components of their per-record
  sum is 12.269..74.042 nT (median 29.8 nT), against a ±50,000 nT signal.
- **17 samples** (2022-11-21..2024-11-10): all seven terms are published as
  exactly 0.0 (+0.0 bit patterns) on every record, so no disturbance correction
  is present in those files. Upstream does not document this (README, DOI
  page). The dates are 20221121, 20230105, 20230219, 20230405, 20230520,
  20230704, 20230818, 20231002, 20231116, 20231231, 20240214, 20240330,
  20240514, 20240628, 20240812, 20240926 and 20241110 (alternating GF1/GF2).

This explains the file-size eras. The ~8 MB files (2022-11..2024-11) are
smaller because each zero-filled `dB_*` array compresses to 9,280 bytes
(4 CVVRs) instead of 0.76–1.74 MB. In a 2022-10-07 vs 2022-11-21 comparison,
the `dB_*` arrays account for 9,575,035 of the 9,629,718-byte difference in
uncompressed image size.

Build reads the seven terms for every file and requires them to be finite
CDF_DOUBLE[3] arrays with the B_NEC record count. It then classifies the file:
either all seven are identically 0.0 or none is all-zero; a mixed state is
fatal. It records the index fields `disturbance_terms_zero` (bool) and
`disturbance_total_rms_nT` (rounded to 1e-3), and fails unless the zero class is
exactly the 17 pinned dates (17 zero / 47 nonzero, also written to
`ingest_stats.json`). Verify re-classifies from raw bytes, recomputes the RMS
with `math.fsum` within 1e-3 nT, and re-checks the 17/47 split. No sample is
dropped or re-selected on this basis (see the homogeneity notes).

## Selection (why these 64 days)

GF1 and GF2 fly the same orbit about 220 km (~30 s) apart, so same-day files of
the two satellites are near-copies with a time shift. The recipe therefore never
takes both satellites on one date and spreads days across the whole mission
(`scripts/select_days.py`, reproduced by `discover.sh`):

1. Candidates are v0201 files covering a complete UTC day (`T000000`..`T235959`
   in the name). Partial-day files are excluded, and so are the months 2024-12
   and 2025-02 (reprocessed to v0202) and 2026-05 (v0201 withdrawn), per the
   README.
2. Slot dates are 2018-06-15 + 45·k days, up to 2026-08-31 (67 slots). The 45-day
   cadence walks through seasons, solar-cycle phase (2019-2020 minimum, 2024-2025
   maximum) and orbital local time.
3. Even slots take GF1 and odd slots take GF2. If that satellite has no candidate
   file on the date, the other satellite's file for the same date is used (2
   cases, 2018-07-30 and 2020-01-21, both in GF2 data gaps). If neither has one, the slot is skipped
   (3 slots in the excluded months).

`sources.tsv` pins the slot, date, satellite, file name, exact size, SHA-256,
Last-Modified, Apache ETag and URL. ISDC publishes no checksum files, so the
SHA-256 values come from the first complete download (2026-10-05): each file
matched the HEAD-pinned size, had the right CDF magic and passed structural
validation. download, build and verify enforce them.

The total is sized to the collection guidance (a bit above 100 MB primary,
50+ natural samples, download under ~1 GB). The upstream population is about
5,700 satellite-days (~80 GB), far beyond the 1 GB cap.

## Decode

Pure standard-library Python (`scripts/cdf3.py`, self-tested on synthetic CDFs
by `scripts/selftest_cdf3.py` before every build and verify):

1. The file magic is `CDF30001 CCCC0001` (whole-file compressed). The CCR at
   byte 8 gives the CPR offset and uncompressed size, and the CPR says GZIP
   (type 5). The GZIP body runs from byte 40; with the uncompressed magic
   prepended it is a CDF v3 image.
2. The CDR declares encoding 1 (network, big-endian). Parse the GDR, then the
   zVDR chain, then the ADR/AEDR chains (global and variable attributes).
3. `B_NEC` is CDF_DOUBLE with zDims [3] and MaxRec 86399 (86398 when one
   epoch is absent). Walk its VXR chain, following `VXRnext` links and nested
   VXRs. Each leaf is a CVVR, a separate GZIP stream (4 blocks in every
   realized file), or a raw VVR. Blocks must cover records 0..MaxRec
   contiguously, with no sparse or padded records.
4. Unpack as `>d` and write as `<d`.

## Missing values and checks

The `B_NEC` FILLVAL is NaN. The policy, shared by build and verify:

- every Timestamp equals the file date's midnight + k·1000 ms with integer k,
  strictly increasing, first k = 0 (00:00:00), last k = 86399 (23:59:59);
- at most 10 lattice epochs may be absent. Upstream omits such a record rather
  than writing a fill value. Timestamp, B_NEC, B_FGM, q_NEC_FGM and B_FLAG
  must have equal record counts;
- all B_NEC values are finite.

The sample keeps exactly the records present, in order, and inserts nothing for
absent epochs. Those are listed per sample in the index field
`missing_epoch_seconds`, so the time axis is recoverable without a timestamp
series. Realized: 60 files are complete; 4 lack exactly one epoch each
(GF1 2019-03-12 at second 2296, GF2 2020-07-19 at 15049, GF1 2023-02-19 at
51046, GF2 2026-06-18 at 65891). Any NaN, infinity, off-lattice or duplicate
epoch, or more than 10 absent epochs, is fatal. Nothing is dropped or imputed.
`B_FLAG` (uint8, semantics not documented in the README) does not remove
values. Its per-day nonzero count is recorded in the index: 0 on most days,
at most 878 records (~1%) on one day.

The first download run applied a stricter rule (exactly 86,400 records) and
quarantined those 4 files as `*.invalid`. download.sh reinstates a
quarantined file only if it matches the pinned size and SHA-256, then
re-validates it under the current rule.

download.sh checks:

- the pinned plan count and bytes;
- README content: license line, DOI, and no reprocessed or withdrawn months
  beyond the three known ones;
- per file: exact size and CDF magic;
- the full CDF structure, file identity attributes (TITLE equals the file stem,
  Project, DOI, License) and the Timestamp lattice. Invalid files are
  quarantined as `*.invalid`.

build.sh additionally checks:

- `LABELS_BNEC`;
- per-component nonconstancy, with every component's values all distinct;
- no float32-exact values;
- |B| within 5,000..80,000 nT (decode sanity);
- the disturbance-term classification and the pinned 17/47 split;
- distinct sample hashes.

It writes `index/<id>/samples.jsonl` (required fields plus shape, record
count, missing_epoch_seconds, axes, component order, min/max computed from the
stored float64, sample and source SHA-256, satellite, date, slot, B_FLAG count,
disturbance_terms_zero, disturbance_total_rms_nT, component_distinct_counts and
float32_exact_values) and
`filtered/<id>/ingest_stats.json`.

verify.sh re-decodes every source file and checks:

- the samples byte for byte, through a separate `array.byteswap` path;
- index fields, min/max and the manifest `sample_count`/`total_size_bytes`;
- that the sample directory matches `sources.tsv`;
- that `B_NEC` equals the rotation of `B_FGM` by the conjugate of the
  scalar-last quaternion `q_NEC_FGM` within 1e-6 nT on every 7th epoch. Across
  all 64 realized samples the maximum error was 6.6e-11 nT. This pins both
  the variable choice and the N,E,C interleave;
- distinct counts, float32-exact counts (via the low 29 mantissa bits), the
  disturbance-term class from raw bytes, the RMS within 1e-3 nT, and the
  17/47 split.

## Homogeneity notes and caveats

- One product (ACAL_CORR v0201), one variable, one unit (nT), one frame (NEC),
  one 1 Hz lattice, the same instrument type (FGM A) and the same GFZ processing
  chain on both satellites.
- The two satellites carry physically different magnetometer units with their
  own monthly calibration parameters. Their differences are of the same order
  as day-to-day variation, not a different regime.
- The README records minor processing changes within v0201: from 2021-04,
  scikit-learn `LinearRegression(normalize=True)`; from 2024-12, CHAOS8 as the
  reference model. Both are calibration-fit details, not changes of quantity
  or scale.
- The 17 zero-correction samples (2022-11-21..2024-11-10) are kept in the same
  family. They share unit, frame, 1 Hz lattice, instrument, calibration chain,
  file layout and value range with the other 47. The missing correction is
  12–74 nT RMS (median ~30 nT) on a ±50,000 nT signal, and their
  second-difference statistics are indistinguishable from the corrected era.
  The per-sample median |Δ²B| is 1.27–2.05 / 1.24–2.19 / 1.19–1.90 nT (N/E/C)
  in the 47 corrected samples and 1.31–2.18 / 1.34–2.13 / 1.24–1.62 nT in the
  17 zero-correction samples. The medians of the per-sample p90 agree within 4%, and those of
  the p99 within 17%. The
  acceptance judge reached the same conclusion: one compression regime,
  disclosed and recorded per sample rather than re-selected. Consumers who need
  only disturbance-corrected days can filter on `disturbance_terms_zero`.
- `B_NEC` is a calibrated product, a rotation of the calibrated `B_FGM`, not raw
  ADC counts. The platform magnetometer is not a science-grade instrument, so
  residual disturbances remain even where corrections are applied, and in the
  17 zero-correction samples the corrections are absent. It is still a genuine
  physical measurement stream at full binary64 precision.

## Files

- `download.sh`, `build.sh`, `verify.sh`: the script contract (support `DATA_DIR`, logs under `$DATA_DIR/logs/<id>/`)
- `discover.sh`: documents how `sources.tsv` was resolved (listings, selection, HEAD-pinned sizes)
- `sources.tsv`: the 64 pinned files
- `scripts/cdf3.py`: CDF v3 reader; `scripts/selftest_cdf3.py`: synthetic-file self-test
- `scripts/select_days.py`: selection rule; `scripts/gracefo_fgm.py`: validate/build/verify
