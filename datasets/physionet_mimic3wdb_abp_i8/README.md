# MIMIC-III Waveform Database: invasive arterial blood pressure channel (int8)

This recipe collects the invasive arterial blood pressure (ABP) channel of 51
adult ICU waveform segments (60 pinned, 9 excluded by the content rule) from the PhysioNet MIMIC-III Waveform Database
1.0. Each sample is one segment's complete ABP channel at 125 Hz, given as
the stored 8-bit WFDB format-80 digits converted to signed int8
(stored byte - 128). One segment is taken per record (patient stay).

- Selection: 60 segments from 60 records, found by walking 2,762 adult
  records.
- Output: 51 samples, 195,628,953 int8 values (195.6 MB). Segment lengths
  run from 526,888 values (70 min) to 19,575,000 (43.5 h); the median is
  2,068,767 (4.6 h).
- Download: 687,268,057 B of `.dat`, plus about 0.8 MB of headers, lists
  and license files.

## Material

- Quantity: the bedside monitor's ABP signal, which is invasive
  arterial-line pressure. Per the release description it is sampled
  uniformly at 125 Hz (8 ms) and not scaled before capture. That differs
  from the ECG channels, which were decimated with a turning-point
  compressor.
- Calibration: one for every sample, `1.25(-100)/mmHg` with ADC resolution
  8. Pressure is (value + 100) / 1.25 mmHg, in 0.8 mmHg steps. The monitor
  output saturates at codes -125..125 (-20..180 mmHg). The 8-bit format
  would also allow ±126/±127, and -128 is the WFDB invalid-sample code; a
  segment containing any of these is excluded (see the keep rule).
- Emitted: only the ABP column. The other columns are read only to validate
  their WFDB checksums: the ECG leads I, II, III, V, AVF, AVL, AVR and MCL1,
  plus PAP (16 segments) and CVP (1 segment).
- Not emitted: header base times (time of day only), master-header ICU
  location comments, and layout headers. download/build/verify never fetch
  the master or layout headers; only the author-time discovery script reads
  them.

### Why only one calibration

ABP in this database comes at many calibrations. In the long segments of
the first 160 adult records the counts were:

- format 16 at `20.4733(307)/mmHg`: the most common;
- format 80 at `1.28(-109)`, `1.06667(-109)`, `1.6(-109)`, `1.25(-100)`,
  `2.4125(-253)`, `3.2(-285)` and others.

Each is a different tick lattice. The recipe keeps exactly one,
`1.25(-100)/mmHg` in format 80, so the family has a single lattice. In
total about 1 record in 46 contributes. A sibling family at `1.28(-109)`,
or at format-16 `20.4733(307)`, would be a separate recipe.

## Selection

Author-time discovery is in `scripts/mimic_discover.py`. It is
re-runnable, network via the curl CLI, small text files only. The result
is pinned in `scripts/mimic_pins.py`.

1. Walk `RECORDS-adults` in file order.
2. Skip a record if:
   - it has no waveform record, only numerics (56 records);
   - its layout header's ABP line is missing or not at gain 1.25/mmHg
     (2,624 records). This is a cheap prefilter: the layout header carries
     one calibration per signal name;
   - it has no qualifying segment (22 records).
3. In each remaining record, take the first segment in master-header order
   (which is chronological) that qualifies:
   - at least 500,000 frames;
   - 125 Hz;
   - every signal in format 80, in the single file `<segment>.dat`;
   - exactly one signal named `ABP`, with gain string `1.25(-100)/mmHg`,
     ADC resolution 8 and ADC zero 0.
4. Stop at 60 records. The last record walked is `30/3045953/`.

The SHA-256 of each kept `.hea` and `.dat` comes from the release
`SHA256SUMS.txt` (639 MB, path-sorted), found by binary search over HTTP
range requests. Each `.dat` size comes from the record directory listing
and equals frames × nsig.

Limitation: all 60 records lie in intermediate directory `30/` (records
3000003-3045953), because the walk stops early in `RECORDS-adults` order.
The 1.25(-100) calibration is concentrated in these early records.
Signal sets are 2-4 signals per segment, with ABP at column index 1 or 2.

## Content policy

Decisions are made on whole segments. No time span inside a kept segment
is cut.

- **Window classes.** These are descriptive and stored per sample. Each
  60 s window is 7,500 frames; the last window may be partial. The first
  matching class wins. Percentiles are nearest-rank over the non-invalid
  codes.

  | class | rule |
  |---|---|
  | invalid | fewer than half the values valid (not -128) |
  | flat | max - min <= 2 codes (<= 1.6 mmHg) |
  | low | median < -75 (< 20 mmHg: zeroing, flushing, disconnected transducer) |
  | pulsatile | p95 - p5 >= 13 codes (about 10.4 mmHg) |
  | damped | otherwise |

- **Keep rule.** A segment is excluded whole if any of these holds:
  - more than 10% of its values are -128;
  - one code holds more than 25% of its values;
  - fewer than 50% of its windows are pulsatile;
  - it has fewer than 32 distinct codes;
  - any ABP value lies outside the monitor range -125..125 (a -128 invalid
    marker, -127, -126, +126 or +127; `MONITOR_MIN_CODE` /
    `MONITOR_MAX_CODE` in `scripts/mimic_pins.py`, re-implemented in
    `mimic_verify.py` with a drift check).

  At least 40 segments must survive.
- **Why the monitor-range rule.** 4 of the 60 pinned segments use the full
  8-bit range with -128 invalid markers: 3013004_0158, 3013395_0001,
  3018045_0013 and 3038577_0007. In all four, the ABP column shows no
  beat-synchronous pulse. There is no autocorrelation peak at 0.34-1.5 s in
  any of 20 evenly spaced 8 s excerpts, while the ECG lead in the same
  frames has a beat period of about 0.6 s. Every other kept segment
  saturates at ±125, and its ABP period matches the ECG period.
  3013004_0158 (median 34 mmHg, 2-3 s slow wave) and 3018045_0013 (swings
  -22..182 mmHg, both rails pegged) previously passed only because a slow,
  large-amplitude wave satisfies the p95-p5 "pulsatile" test. This evidence
  comes from the acceptance review. The rule is the monitor range, not an
  autocorrelation or beat-detection threshold: genuine irregular-rhythm
  segments (3001557_0005, 3034353_0008, 3038595_0004) score low on
  autocorrelation although their ABP tracks the ECG.
- **Saturation and missing values.** Nothing is dropped, imputed or clipped
  inside a kept segment. Values at the saturation codes +125 (180 mmHg) and
  -125 (-20 mmHg) are kept in place and counted (`saturation_high_count`,
  `saturation_low_count`). Code 125 holds about 0.82% of kept values: at
  most 9.07% in 3001920_0037, and it is the mode code in 8 samples. Most of
  it comes from pegged stretches of up to 88,847 consecutive frames (about
  11.8 min, in 3009600_0002), consistent with line flush, blood-sampling or
  stopcock events. Those stretches are never cut. Code -125 holds 0.025%.
  Flat, damped and low stretches inside kept segments also stay in the
  sample. Because of the monitor-range rule, every kept sample has
  `invalid_sample_count` = 0 and `outside_monitor_range_count` = 0.

## Source and rights

- Source: `https://physionet.org/files/mimic3wdb/1.0/`, version 1.0,
  published 2020-04-07. The numbered records are identical to MIMIC-II
  Waveform Database 3.2.
- License: Open Data Commons Open Database License v1.0. The project page
  states: "Access Policy: Anyone can access the files, as long as they
  conform to the terms of the specified license. License: Open Data Commons
  Open Database License v1.0".
  - `LICENSE.txt` (ODbL text) is pinned by hash.
  - `download.sh` saves the landing page and requires the access-policy
    sentence, the license name and the DOI.
  - mimic3wdb is open access: no credentialing and no data use agreement,
    unlike the MIMIC-III Clinical Database.
  - ODbL is share-alike. The derived samples must be credited and, if
    publicly used or redistributed, kept under ODbL. Accepted ODbL
    precedent: the OSM, taginfo, OpenFlights and NCLT recipes.
- Citation: Moody B, Moody G, Villarroel M, Clifford GD, Silva I.
  MIMIC-III Waveform Database (version 1.0), PhysioNet (2020),
  doi:10.13026/c2607m. Also Johnson AEW et al., Sci Data 3:160035 (2016),
  and the standard PhysioNet citation.
- Safety:
  - The data are de-identified clinical waveforms: IRB-approved, consent
    waived because protected health information was deidentified.
  - Only ABP stored values are emitted.
  - `verify.sh` fails if ICU location or time-of-day text appears in the
    index or stats.

## Novelty

`tools/autocollect/novelty.py --url mimic3wdb --terms mimic "arterial blood
pressure" ABP` finds no MIMIC recipe or registry entry. The only ABP match
is `physionet_charis_icp_i16`, which is a 16-bit intracranial-pressure
channel; CHARIS's ABP was deliberately not emitted. The existing 8-bit
physiological family is MIT-BIH ECG, a different waveform. The
clinical-monitor waveforms in the corpus are all 16-bit: BIDMC PPG/resp
and CHARIS ICP. The same host, physionet.org, serves several accepted
recipes, so the driver's archive sign-off applies.

Byte-level check (`tools/autocollect/zlsim.py gate`, 2026-10-09): verdict
**OK** (not redundant, but not STRONG), measured on the earlier
53-sample build that still included 3013004_0158 and 3018045_0013. Own held-out compression ratio is
4.56. The nearest feature distance is 0.080 (AlphaEarth i8 embeddings,
cross-compression loss 40%). The downstream MIT-BIH MLII u8 ECG family is
at distance 0.11, and its compressor comes within 2.8% of this family's
own. So it is compression-equivalent but outside the 0.05 feature-distance
threshold. That makes ECG the closest material in compression terms, as
expected for another 125 Hz-class 8-bit physiological waveform.

## Running

From the repository root:

```bash
bash staging/physionet_mimic3wdb_abp_i8/download.sh   # ~688 MB, 60 resumable .dat GETs + 63 small files
bash staging/physionet_mimic3wdb_abp_i8/build.sh
bash staging/physionet_mimic3wdb_abp_i8/verify.sh
```

- `download.sh`:
  - fetches `RECORDS-adults`, `LICENSE.txt`, the 60 segment headers and the
    60 `.dat` files, all pinned by size and SHA-256;
  - fetches `.dat` files with `curl -fL -C - --retry 10 --speed-limit 1024
    --speed-time 120` into `.part`, with no `--max-time` and 5 resume
    attempts;
  - saves the landing page.

  `scripts/mimic_download_check.py` then re-hashes everything and
  validates every header against the pins: geometry, ABP index,
  calibration, initial value and checksum. It writes
  `download_inventory.json`.
- `build.sh` (`scripts/mimic_build.py`):
  - self-tests on a synthetic segment;
  - per segment: parses and checks the header, then streams the `.dat` in
    1,050,000-frame chunks;
  - checks every signal's 16-bit WFDB checksum and the ABP initial value;
  - writes `<segment>.bin` (int8);
  - computes the window classes and applies the keep rule.
- `verify.sh` (`scripts/mimic_verify.py`) works independently:
  - regex header tokenizer;
  - whole-file `array('b')` strided decode;
  - sorted-list window statistics;
  - its own copy of the policy constants, with a drift check against the
    pins.

  It compares sample bytes, every index field, the stats, the keep and
  exclude lists, the manifest totals, stray files, payload uniqueness and
  the floors.

## Outputs

- Samples: `.data/samples/physionet_mimic3wdb_abp_i8/mimic3wdb_abp_fmt80_i8/<segment>.bin`.
- Index: `.data/index/physionet_mimic3wdb_abp_i8/samples.jsonl`. Each row
  has the standard fields plus:
  - record, segment, source `.dat`, nsig, ABP column index;
  - calibration;
  - WFDB checksum and initial value;
  - min/max, distinct codes, mode code and mode share;
  - `invalid_sample_count`, `outside_monitor_range_count`,
    `saturation_high_count` (code +125) and `saturation_low_count`
    (code -125);
  - the five `windows_<class>` counts;
  - the sample SHA-256.
- Stats: `.data/filtered/physionet_mimic3wdb_abp_i8/ingest_stats.json`
  (kept and excluded segments with reasons, totals, and the aggregate
  SHA-256).
- Logs: `.data/logs/physionet_mimic3wdb_abp_i8/`.

## Realized scope

From the download, build and verify of 2026-10-09.

- Download (autocollect driver): 688,090,604 B under
  `.data/*/physionet_mimic3wdb_abp_i8`; all 122 pinned files matched size
  and SHA-256, and every header matched the pins.
- Integrity: for all 60 pinned segments, every signal's WFDB 16-bit
  checksum and the ABP initial value match the header; every `.dat` is
  frames × nsig bytes.
- Output: 51 samples, 195,628,953 values, 195,628,953 bytes; median
  2,068,767 values (range 526,888-19,575,000). Aggregate sample SHA-256
  (over `segment:sha256` lines):
  `bbdcf5e3a1cd4da00e63d2424707efbfca57648e29d5e2515ef5213815d3cb85`.
- Content of kept samples:
  - 185 to 251 distinct codes per sample. The largest single-code share is
    12.5% (3042934_0005, code -119 ≈ 0.8 mmHg: a zeroed/low stretch).
  - Window classes over 26,101 windows: 25,940 pulsatile (99.4%), 104 flat,
    41 low, 16 damped, 0 invalid.
  - No value outside -125..125 and no -128 invalid code in any kept
    sample.
  - Code +125 (180 mmHg saturation) holds 1,607,325 values (0.82%), at
    most 9.07% in 3001920_0037. Code -125 holds 48,881 values (0.025%).
- Excluded whole (no sample, listed with reasons in `ingest_stats.json`):

  | segment | reason | detail |
  |---|---|---|
  | 3012395_0001 | mode share 0.308 | code 125 (180 mmHg) held flat in 187 of 627 windows |
  | 3013395_0001 | mode share 0.762, pulsatile 0.24; outside monitor range (262,334) | flat at code -65 (28 mmHg) in 491 of 649 windows |
  | 3031663_0003 | mode share 0.487, pulsatile 0.46 | flat at code -125 (-20 mmHg) |
  | 3033264_0007 | mode share 0.998, pulsatile 0.004 | flat at code 125 almost throughout |
  | 3038577_0007 | invalid fraction 0.166; outside monitor range | 2,385,932 -128 codes; 5,304,269 values outside -125..125 |
  | 3042059_0028 | pulsatile 0.43 | 55 flat and 22 low of 138 windows |
  | 3043821_0010 | mode share 0.607, pulsatile 0 | flat at code -125 |
  | 3013004_0158 | outside monitor range (20,411) | -128 markers; smooth 2-3 s slow wave, median 34 mmHg, no cardiac component |
  | 3018045_0013 | outside monitor range (643,239) | swings -22..182 mmHg with both 8-bit rails pegged; no beat-synchronous pulse |
