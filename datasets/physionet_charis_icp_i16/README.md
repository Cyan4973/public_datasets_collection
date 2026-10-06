# PhysioNet CHARIS intracranial pressure channel waveforms (int16)

This recipe collects the intracranial pressure (ICP) channel of the 9
majority-ICP records of the PhysioNet CHARIS database 1.0.0: multi-day
neuro-ICU recordings, one per patient, of patients with traumatic brain
injury or other acute brain injury. Each kept record becomes one sample:
the record's complete ICP channel at 50 Hz, as the publisher's auto-scaled
WFDB format-16 stored values, little-endian int16, unchanged.

The release has 13 records. charis8, charis9, charis10 and charis12 are
excluded because less than half of their ICP channel carries an ICP
pressure waveform (see below).

- Output: 9 samples, 204,043,652 values, 408,087,304 bytes.
- Sample lengths: 7,199,999 values (40 h) to 67,499,794 values (375 h).
- Median: 17,095,224 values (charis3, 95 h).

## Material

- Quantity: the ICP channel. This is the analog pressure output of a GE
  TRAM-rac 4A patient monitor, low-passed at 25 Hz and sampled at 50 Hz.
  The transducer is an intraparenchymal Camino micro-transducer or, in some
  patients, a ventriculostomy.
- Not emitted:
  - the ABP and ECG signals, which are read only to validate checksums;
  - all header comments: age, sex, diagnosis group, outcome, and charis9's
    signal-quality note.

  ABP would be a separate quantity and is deliberately left out; it could
  be a sibling family.

### What the stored values are

The emitted integers are the publisher's WFDB stored values. They are not
raw monitor ADC output.

- **Native scale.** The native monitor quantization is 60.8182 codes/mmHg.
  Two pieces of evidence:
  - the excluded charis12 is stored unscaled, with ICP and ABP headers of
    60.8182(-392)/mmHg;
  - every record's ECG gain, 6081.5219 or 6081.8245 per mV, is on the same
    scale.
- **Auto-scaling.** All 9 kept records were auto-scaled by the publisher:
  the ICP and ABP channels were stretched to the full int16 range, so the
  physical minimum and maximum map to -32767 and +32767. Each kept ICP
  channel therefore contains exactly one +32767 and one -32767 value. ECG
  was not stretched and has thousands of rail values.
- **Stretch.** The header gain exceeds the native one by
  r = gain / 60.8182 = 1.3193-1.6127. The stored values sit on a stretched
  lattice that leaves at least about 1 - 1/r of the integer codes in the ICP
  band unused.

Index fields record both effects:

- `stretch_vs_native` = round(gain / 60.8182, 4);
- `unused_code_fraction_0_40mmhg`: the share of integer codes from baseline
  to floor(baseline + 40 × gain) that never occur; 0.242-0.506 across the
  kept records.

The unused fraction equals 1 - 1/r to 3 decimals in charis1, 2, 7, 11 and
13, is 0.267 vs 0.261 in charis6, and is higher in charis3, 4 and 5, where
part of the 0-40 mmHg band is never reached.

| record | gain (codes/mmHg) | baseline | stretch r | 1 - 1/r | unused codes 0-40 mmHg | status |
|---|---|---|---|---|---|---|
| charis1 | 94.8784 | -2316 | 1.5600 | 0.359 | 0.359 | kept |
| charis2 | 82.1325 | -310 | 1.3505 | 0.260 | 0.260 | kept |
| charis3 | 80.2357 | 64 | 1.3193 | 0.242 | 0.319 | kept |
| charis4 | 84.0552 | -5 | 1.3821 | 0.276 | 0.506 | kept |
| charis5 | 83.1953 | -609 | 1.3679 | 0.269 | 0.366 | kept |
| charis6 | 82.3123 | -212 | 1.3534 | 0.261 | 0.267 | kept |
| charis7 | 98.0796 | -2437 | 1.6127 | 0.380 | 0.380 | kept |
| charis8 | 83.0946 | 172 | 1.3663 | 0.268 | 0.268* | excluded |
| charis9 | 129.2474 | -13789 | 2.1251 | 0.529 | 0.530* | excluded |
| charis10 | 80.2506 | -179 | 1.3195 | 0.242 | 0.249* | excluded |
| charis11 | 85.8882 | -576 | 1.4122 | 0.292 | 0.292 | kept |
| charis12 | 60.8182 | -392 | 1.0000 | 0.000 | 0.033* | excluded |
| charis13 | 80.2781 | -3 | 1.3200 | 0.242 | 0.242 | kept |

\* Excluded-record figures come from a one-off decode of their `.dat` files
with the same build decoder. They are not recipe outputs.

Pressure in mmHg is (value - baseline) / gain, with the header calibration
kept as index metadata (`adc_gain_per_mmhg`, `adc_baseline`; "ADC units" is
WFDB's term for stored digital values). The recipe emits the stored values
unchanged. It does not rescale them to the native lattice, and does not
clip, invert or cut them.

## Content caveat: the ICP channel is not ICP throughout

These are unedited multi-day ICU recordings, and the channel labelled ICP
does not always carry ICP. Spot probes (12 windows of 40 s per record) found
these regimes:

- **Physiological ICP:** medians of roughly 0-35 mmHg.
- **Arterial blood pressure on the ICP input:** median about 120 mmHg,
  swing about 60-200 mmHg. At the same time the ABP channel reads about
  0 mmHg. Seen in charis8 at 30%, 55% and 73% of the recording, charis2 at
  91%, charis11 at 91% and 100%, and charis9 at 50% and 80%. In charis7
  both channels carried arterial-like waveforms at once (ICP ~120, ABP
  ~95 mmHg) at 91% and 100%.
- **Pegged output near 100 mmHg:** charis3, charis5 and charis10.
- **White noise around a level inside the ICP band, with no pressure
  waveform:** most of charis12, about a third of charis9, and small shares
  elsewhere.
- **Disconnected or zero output near 0 mmHg:** the tail of charis8 and the
  end of charis13.
- **Crosstalk:** about 300 mmHg, correlated 0.996-0.998 with ABP, at the
  ends of charis2 and charis10.

### Full-record diagnostics

`build.sh` computes these diagnostics over every complete emitted channel,
and `verify.sh` re-derives them with its own implementation. They are
descriptive only: no segment is cut on them. Records are only kept or
excluded as a whole.

- Per value: codes outside -10..100 mmHg, using each record's header gain
  and baseline.
- Per 60 s window (3,000 samples; the final window may be partial): one
  mutually exclusive class, from the window median m, peak-to-peak range,
  5th-95th percentile spread s (all in mmHg), and lag-1 autocorrelation r1
  of the window's codes. r1 is evaluated exactly in integers: with
  y_i = n·x_i - Σx, a waveform is present iff 2·Σ y_i·y_(i+1) ≥ Σ y_i².
  For a smooth signal plus white noise r1 ≈ S/(S+N), so r1 ≥ 0.5 means
  waveform power at least equals the sample-noise power. Real ICP windows
  sit at r1 ≥ 0.9.

  | class (index field) | rule |
  |---|---|
  | plausible ICP: pressure waveform present (`windows_plausible_icp`) | -10 ≤ m ≤ 50, peak-to-peak ≥ 1, r1 ≥ 0.5 |
  | ICP-band noise (`windows_icp_range_noise`) | -10 ≤ m ≤ 50, peak-to-peak ≥ 1, r1 < 0.5 (white noise around a level) |
  | flat, ICP range (`windows_flat_icp_range`) | -10 ≤ m ≤ 50, peak-to-peak < 1 (disconnected/zeroed) |
  | arterial blood pressure on the ICP input (`windows_high_pulsatile`) | 50 < m ≤ 250, s ≥ 20 |
  | pegged output (`windows_high_flat`) | 50 < m ≤ 250, s < 2 |
  | other high (`windows_high_other`) | 50 < m ≤ 250, otherwise |
  | above 250 mmHg (`windows_very_high`) | m > 250 (crosstalk / out of range) |
  | negative (`windows_negative`) | m < -10 |

Per-record results for all 13 records. Kept rows are recipe outputs.
Excluded rows come from the same one-off decode noted above. "Other" is
other high plus negative. "Wraps" is explained under "Rail values and
wrap-like jumps".

| record | status | values | hours | distinct codes | outside -10..100 mmHg | plausible ICP (waveform) | ICP-band noise | arterial BP on ICP input | pegged | >250 mmHg | flat (ICP range) | other | wraps |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| charis1 | kept | 12,239,851 | 68 | 12,866 | 0.1% | 92.0% | 1.4% | 0.2% | 3.8% | 0.0% | 0.0% | 2.5% | 8 |
| charis2 | kept | 67,499,794 | 375 | 24,063 | 10.3% | 85.1% | 0.8% | 12.4% | 0.0% | 1.3% | 0.2% | 0.3% | 4 |
| charis3 | kept | 17,095,224 | 95 | 10,242 | 46.0% | 52.1% | 0.2% | 7.9% | 37.9% | 1.7% | 0.1% | 0.1% | 5 |
| charis4 | kept | 7,199,999 | 40 | 20,631 | 2.4% | 97.2% | 0.2% | 1.1% | 0.0% | 1.5% | 0.0% | 0.0% | 8 |
| charis5 | kept | 35,999,722 | 200 | 10,471 | 13.0% | 83.3% | 0.0% | 0.8% | 15.5% | 0.0% | 0.2% | 0.1% | 65 |
| charis6 | kept | 8,279,982 | 46 | 19,743 | 1.3% | 98.7% | 0.0% | 0.7% | 0.0% | 0.6% | 0.0% | 0.0% | 1 |
| charis7 | kept | 24,180,734 | 134 | 22,887 | 13.4% | 84.2% | 0.4% | 14.6% | 0.0% | 0.8% | 0.0% | 0.0% | 3 |
| charis8 | **excluded** | 17,169,957 | 95 | 23,389 | 33.3% | 47.7% | 3.4% | 43.3% | 0.0% | 1.4% | 4.1% | 0.1% | 3 |
| charis9 | **excluded** | 30,779,979 | 171 | 25,004 | 43.2% | 8.6% | 32.1% | 56.3% | 0.0% | 0.5% | 2.6% | 0.0% | 24 |
| charis10 | **excluded** | 21,278,773 | 118 | 7,738 | 37.3% | 20.0% | 0.0% | 5.3% | 38.4% | 14.3% | 10.6% | 11.5% | 1 |
| charis11 | kept | 17,328,390 | 96 | 24,336 | 26.0% | 60.7% | 3.3% | 33.7% | 0.4% | 1.8% | 0.0% | 0.1% | 5 |
| charis12 | **excluded** | 20,545,133 | 114 | 25,051 | 2.0% | 38.2% | 57.5% | 1.1% | 0.0% | 1.0% | 2.0% | 0.3% | 12 |
| charis13 | kept | 14,219,956 | 79 | 25,619 | 8.4% | 88.2% | 1.3% | 1.0% | 4.4% | 3.2% | 0.5% | 1.4% | 22 |

Over the 9 kept records (68,017 windows):

| class | windows | share |
|---|---|---|
| plausible ICP (waveform present) | 55,391 | 81.44% |
| arterial blood pressure on the ICP input | 6,561 | 9.65% |
| pegged output | 4,411 | 6.49% |
| above 250 mmHg | 757 | 1.11% |
| ICP-band noise | 536 | 0.79% |
| other high | 213 | 0.31% |
| flat, ICP range | 96 | 0.14% |
| negative | 52 | 0.08% |

14.09% of the kept values (fraction 0.140889) lie outside -10..100 mmHg.

### Exclusions

The exclusions are pinned as `EXCLUDED_RECORDS` in `scripts/charis_pins.py`.
`verify.sh` keeps its own copy of the list. It checks that no excluded
record has a sample file or an index row, and that every kept record has at
least 50% plausible-ICP windows under the waveform test. The minimum is
charis3 at 52.1%.

- **charis8**: 47.7% plausible-ICP windows. 43.3% are arterial blood
  pressure on the ICP input while ABP reads about 0 mmHg; 4.1% flat and
  3.4% ICP-band noise.
- **charis12**: 38.2% plausible. 57.5% of windows are in the ICP band but
  are white noise around a level (r1 < 0.5), with no cardiac component
  while ABP is pulsatile. It is also the only unscaled native-lattice
  record (stretch 1.0).
- **charis10**: 20.0% plausible. Pegged output at about 101 mmHg (38.4% of
  windows), >250 mmHg crosstalk (14.3%) and flat or zero output (10.6%).
- **charis9**: 8.6% plausible under the waveform test (40.7% without it;
  32.1% are ICP-band noise). 56.3% carry arterial blood pressure on the ICP
  input while ABP reads about 0 mmHg. Its header note says "Intermittent,
  discontinuous ICP signal". It is the calibration outlier, with stretch
  2.125 and baseline -13789.

All 13 headers are still fetched and validated, and all 27 SHA256SUMS.txt
entries are compared with the pins. The four excluded `.dat` files
(538,643,052 B) are not downloaded, and copies left by earlier runs are
ignored.

Kept records are not edited inside. charis3 (52.1% plausible) keeps its
pegged stretch, and charis11 (60.7%) keeps its arterial stretch. Cutting
segments would need a local heuristic classifier and would shard the
natural record.

### Rail values and wrap-like jumps

- No -32768 (WFDB invalid) code occurs in the kept data.
- The single +32767 and -32767 in each kept record are that channel's
  auto-scaled physical extremes.
- Separately, `wrap_like_jumps` counts adjacent values more than 32,768
  codes apart: 121 across the kept records, 1 to 65 per record. An example
  is charis2's run 29700, 31361, 32767, -32767, -32338. In charis2, 4 and 6
  the record's maximum and minimum are adjacent samples at such a jump.
- These jumps are an observed artifact in the published files (all WFDB
  checksums match) and are kept as is.

## Novelty

This is a new quantity. `tools/autocollect/novelty.py` finds no
intracranial or arterial pressure waveform at any width in local recipes,
the registry, the ledger, or the downstream corpus. The source host is
shared with other PhysioNet recipes:

- `physionet_bidmc_ppg_resp_i16`: PPG and respiration at 125 Hz;
- `physionet_circor_pcg_i16`: heart sounds;
- the MIT-BIH and PTB-XL ECG recipes, and the EEG recipes.

None of them is a pressure-transducer channel.

## Source and rights

- Source: the anonymous PhysioNet open-data bucket,
  `https://physionet-open.s3.amazonaws.com/charisdb/1.0.0/`. This is a
  mirror of `physionet.org/files/charisdb/1.0.0/`, version 1.0.0, published
  2017-01-19.
- License: Open Data Commons Attribution License v1.0. The release has no
  LICENSE file. The project page states: "Access Policy: Anyone can access
  the files, as long as they conform to the terms of the specified license.
  License: Open Data Commons Attribution License v1.0". It links
  `/content/charisdb/view-license/1.0.0/`, which carries the ODC-By text.
  `download.sh` saves both pages and requires those statements. This is the
  same license and access class as the accepted BIDMC and CirCor recipes.
- Attribution:
  - Kim N, Krasner A, Kosinski C, Wininger M, Qadri M, Kappus Z, Danish S,
    Craelius W. "Trending autoregulatory indices during treatment for
    traumatic brain injury". J Clin Monit Comput 30:821 (2016),
    doi:10.1007/s10877-015-9779-3.
  - The dataset DOI 10.13026/C24G6F.
  - The standard PhysioNet citation.
- Safety: de-identified human clinical data. Only ICP-channel stored values
  are emitted. `verify.sh` fails if demographic or outcome header text (age,
  sex, diagnoses, outcome) appears in the index or stats. The only
  header-derived text in the outputs is the charis9 exclusion reason, which
  quotes its signal-quality note.

## Running

Run from the repository root:

```bash
bash staging/physionet_charis_icp_i16/download.sh   # ~1.22 GB, 9 large + 17 small GETs
bash staging/physionet_charis_icp_i16/build.sh
bash staging/physionet_charis_icp_i16/verify.sh
```

### `download.sh`

1. Fetches `SHA256SUMS.txt`, `RECORDS` and all 13 `.hea` headers. Each is
   pinned by size and SHA-256 in `scripts/charis_pins.py`.
2. Fetches the 9 kept `.dat` files (1,224,261,912 B). The pin table has 24
   files in total.
   - `curl -fL -C - --retry 10 --speed-limit 1024 --speed-time 120` into
     `.part`, with no `--max-time`;
   - up to 5 resume attempts per file;
   - an oversized or hash-mismatched partial file is restarted;
   - a file is promoted only when its size and SHA-256 match.
3. Saves the two license-evidence pages and requires their license text.
4. `scripts/charis_download_check.py` then checks:
   - SHA256SUMS.txt lists exactly the expected 27 files with the pinned
     hashes, including the four excluded `.dat` files;
   - RECORDS names exactly charis1..13 (upstream order starts at charis10);
   - every header declares 3 signals ABP/ECG/ICP, format 16, 50 Hz and the
     pinned nsamp;
   - every kept `.dat` is nsamp × 6 bytes and matches SHA256SUMS.txt.

   It writes `download_inventory.json`, which lists the 9 kept records and
   the 4 exclusions with their reasons.

### `build.sh`

Uses only local files. It first self-tests the decoder on a synthetic
record. The synthetic record has a smooth in-band waveform window, a
high-pressure window, a ±30-code in-band white-noise window, a flat
partial window, wraps (one across a chunk boundary), and corrupted
variants that must be rejected.

Then, for each kept record in canonical order (charis1-7, 11, 13):

1. Parses the header, discarding comments.
2. Checks the pinned ICP gain, baseline and checksum.
3. Streams the `.dat` in whole-frame chunks: hashes it, sums all three
   signals for their WFDB checksums (16-bit sum), and writes every third
   int16 starting at index 2.
4. Accumulates the diagnostics. The r1 test uses an algebraic integer form
   built from Σx_i·x_(i+1) and Σx_i².

A record fails the build on any checksum, size or calibration mismatch, if
its channel is degenerate, or if it is a kept record below 50%
plausible-ICP windows.

### `verify.sh`

Self-tests its own decoder on the same synthetic record, then re-derives
every sample independently:

- a regex header tokenizer;
- a byte-level de-interleave (bytes 4-5 of each 6-byte frame);
- `struct` decoding;
- bisect counts on sorted windows;
- r1 in the direct y-form;
- set-based unused-code counts.

It re-hashes the sources against SHA256SUMS.txt, re-checks all three WFDB
checksums, and compares:

- sample bytes;
- every index field;
- the ingest stats, including the kept and excluded lists;
- the manifest `sample_count` and `total_size_bytes`.

It also checks that there are no stray files, no excluded-record samples,
and no demographic or outcome header text, and that every kept record has
at least 50% plausible-ICP windows.

## Outputs

- Samples: `.data/samples/physionet_charis_icp_i16/charis_icp_channel_adc_i16/charisN.bin`
  (9 files).
- Index: `.data/index/physionet_charis_icp_i16/samples.jsonl`. Each row has
  the standard fields plus:
  - record ID and calibration (`adc_gain_per_mmhg`, `adc_baseline`, `units`);
  - `stretch_vs_native` and `unused_code_fraction_0_40mmhg`;
  - min/max and distinct count;
  - WFDB checksum and SHA-256;
  - the diagnostics above: out-of-range value counts, the eight
    `windows_<class>` counts, `invalid_sample_count`,
    `positive_rail_count`, `negative_rail_count` and `wrap_like_jumps`.
- Stats: `.data/filtered/physionet_charis_icp_i16/ingest_stats.json`. This
  includes the kept and excluded lists, the checksums of all three signals,
  the header initial-value fields, and the first frame. The header
  initial-value field is 0 for every signal although first samples are
  non-zero; WFDB readers ignore it for format 16, so the recipe records it
  but does not check it.
- Logs: `.data/logs/physionet_charis_icp_i16/`

## Realized scope

From the download, build and verify of 2026-10-06.

- Download (by the autocollect driver, current `download.sh`):
  - 5 s, all cache hits;
  - all 13 headers and the 9 kept `.dat` files re-validated against the
    pins and SHA256SUMS.txt;
  - no fetch of `charis8.dat`, `charis9.dat`, `charis10.dat` or
    `charis12.dat`;
  - the inventory lists 9 kept records and 4 exclusions.
- The 2,171,168,001 bytes under `.data/*/physionet_charis_icp_i16` at that
  point include the built samples and the four excluded `.dat` copies left
  from earlier full-population downloads. A fresh run downloads about
  1.22 GB.

- Output: 9 samples, 204,043,652 int16 values, 408,087,304 bytes.
  - Median sample: 17,095,224 values (charis3). Range: 7,199,999 to
    67,499,794.
  - Aggregate sample SHA-256 (over the `record:sha256` lines):
    `e6248950384520292a76f076757129f3667509843d1ef249d368e6e0bab869ef`.
- Integrity:
  - every record's length equals the header nsamp;
  - the WFDB checksums of all 27 signals (9 records × ABP/ECG/ICP) match
    their headers;
  - the ICP gain, baseline and checksum match the pins;
  - all 9 sample payloads are distinct.
- Content:
  - 10,242 to 25,619 distinct codes per record;
  - exactly one +32767 and one -32767 per record, and no -32768;
  - 81.44% plausible-ICP (waveform) windows overall, with every kept record
    at least 52.1%;
  - 14.09% of values outside -10..100 mmHg;
  - 121 wrap-like jumps.
