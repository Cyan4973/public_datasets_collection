# PhysioNet GRABMyo forearm/wrist surface EMG gesture trials (int16)

This recipe collects 731 hand-gesture trials from GRABMyo 1.1.0 on PhysioNet
(Gesture Recognition and Biometrics ElectroMyogram). That is Session 1,
trial 1 of every participant × gesture: 43 participants × 17 gestures.

Each trial becomes one sample: 5 s of 28-channel surface EMG at 2048 Hz,
stored frame-interleaved as 10,240 frames × 28 channels of raw little-endian
int16. That is 286,720 values (573,440 B) per sample, and about 419 MB in
total.

## Material

- Device: OT Bioelettronica EMGUSB2+ amplifier, gain 500, 2048 Hz, with
  pre-gelled Ambu AM-N00S/E electrodes (from the Sci Data paper).
- Channels kept, in source column order:
  - `F1`-`F16`: forearm, two rings of eight electrodes 2 cm apart;
  - `W1`-`W6` and `W7`-`W12`: wrist, two rings of six.

  The project page says the 28 electrodes were recorded "in a bipolar
  configuration (8+8 for the forearm and 6+6 for the wrist in the form of 4
  rings)". The card's earlier "monopolar" wording described the electrode
  type, not the channel montage.
- Channels dropped: `U1`-`U4` (source columns 17, 24, 25, 32). The project
  page lists them as unused inputs "provided to distinguish the rings of
  electrode setup". In the probes they carry only ~40-55 µV of noise.
- Gestures (from `MotionSequence.txt`), 1-17:
  1. lateral prehension
  2. thumb adduction
  3. thumb-little opposition
  4. thumb-index opposition
  5. thumb-index extension
  6. thumb-little extension
  7. index-middle extension
  8. little finger extension
  9. index finger extension
  10. thumb extension
  11. wrist extension
  12. wrist flexion
  13. forearm supination
  14. forearm pronation
  15. hand open
  16. hand close
  17. Rest
- Scope: Session 1 (day 1) and trial 1 only. Sessions 2-3 (days 8 and 29)
  and trials 2-7 use the same people, gestures and setup. They are not
  downloaded. Taking one trial per participant × gesture keeps the download
  near 0.49 GB (the full release is ~10.1 GB of `.dat`) and the output near
  420 MB (versus ~8.8 GB for all 15,351 trials).

All 731 trials come from one study, one amplifier, one electrode montage,
one sampling rate and one publisher-side encoding. They measure one quantity.

## Encoding: read this before judging width honesty

The emitted values are exactly the int16 values stored in the published
WFDB format-16 `.dat` files. The recipe does no local rescaling, filtering
or resampling. These are **not native amplifier ADC codes**:

1. The paper says the signals were band-pass filtered (10-500 Hz, 4th-order
   Butterworth) and notch-filtered at 60 Hz. Probe spectra show the 60 Hz
   notch, almost no power below about 8 Hz, and roll-off above 500 Hz. The
   published waveform is the filtered float signal.
2. For PhysioNet the publisher converted it to WFDB, "a *.dat file
   containing the signed 16 bit quantized value and *.hea file … containing
   the scaling factors" (paper). The scaling is wfdb-style min/max
   auto-scaling, per file and per channel. Across all 20,468 kept channels:
   - every minimum is -32767 (19,831 channels) or -32766 (637);
   - every maximum is 32763-32766;
   - each extreme occurs exactly once per channel, so there are no clipping
     runs.

   The gain is a non-integer (for example `109223.81106521016(4352)/mV`),
   and the baseline is a per-channel integer.

Consequences:

- In physical units the code scale differs between channels and trials. The
  gain runs from 7.1e3 to 3.4e6 codes/mV (median 1.25e5; 5th-95th
  percentile 3.8e4-5.4e5). The physical spread is wide:
  - gesture-trial channels: 31-9,230 µV peak-to-peak (median 551 µV);
  - Rest-trial channels: 19-1,487 µV (median 102 µV).
- In code space every channel is the same kind of signal: a full-range
  16-bit quantization of one filtered sEMG waveform.
  - Codes are dense, step 1, with no lattice or upsampling gaps:
    3,562-9,176 distinct values per 10,240-sample channel (median 8,102).
  - The per-channel code standard deviation is 1,432-12,395 (median 6,327).
    The narrowest channels are mostly Rest trials, plus a few gesture
    channels with heavy-tailed transients (inter-quartile range below the
    standard deviation).
- Each index row keeps the per-channel `adc_gain_per_mv` and `baseline` as
  auxiliary metadata, so physical mV = (code − baseline) / gain stays
  recoverable. They are not emitted as samples.

The Rest gesture (17) is kept. Its channels are low-amplitude baseline EMG
that the auto-scaling stretches to full range, just like the U channels. They
are real electrode recordings, unlike U1-U4. They make up 43 of the 731
samples (5.9%).

## Novelty

This is new content in a known modality, and new as a 16-bit source:

- The only EMG elsewhere is `uci_emg_gestures_i8` locally and
  `semg_channel_i8` downstream: Thalmic Myo armband int8 codes at 200 Hz,
  8 channels.
- `tools/autocollect/novelty.py` found no GRABMyo, and no 16-bit EMG,
  locally, in staging, in the registry, in the ledger or downstream.
- GRABMyo differs from the Myo set in device (a lab amplifier versus a
  consumer armband), rate (2048 versus 200 Hz), channel count (28 versus 8),
  width and encoding.

Other PhysioNet waveforms in the corpus are different quantities:

- ECG: MIT-BIH, PTB-XL;
- EEG: CHB-MIT, EEG motor imagery;
- PPG/respiration: BIDMC;
- phonocardiograms: CirCor;
- staged drafts: CHARIS ICP and TPEHG EHG.

## Source and rights

- Source: the anonymous PhysioNet open-data bucket
  `https://physionet-open.s3.amazonaws.com/grabmyo/1.1.0/`, a mirror of
  `physionet.org/files/grabmyo/1.1.0/`. Version 1.1.0 is the latest
  (1.0.0-1.0.2 also exist).
- License: CC BY 4.0. The project page's Files section says "License (for
  files): Creative Commons Attribution 4.0 International Public License",
  and access is open with no credentialing.
  - The release `LICENSE.txt` (sha256 `9a78e7f2…`, listed in
    `SHA256SUMS.txt`) is the CC BY 4.0 legal code. `download.sh` pins it and
    checks its first line.
  - The bundled `readme.txt` names the ODC Attribution License v1.0 instead.
    Both licenses are attribution-only.
- Attribution:
  - Jiang, Pradhan & He (2024), GRABMyo v1.1.0, PhysioNet,
    doi:10.13026/89dm-f662;
  - Pradhan, He & Jiang (2022), Sci Data 9:733,
    doi:10.1038/s41597-022-01836-y;
  - Goldberger et al. (2000), PhysioNet.
- Safety: physiological recordings of healthy volunteers, named only by
  numeric participant ID. `subject-info.csv` (anthropometrics) is not
  downloaded. The project studies these signals as a within-dataset
  biometric, so treat them as pseudonymous.

## Running

Run from the repository root:

```bash
bash staging/physionet_grabmyo_semg_i16/download.sh   # ~486 MB, 1,466 GETs
bash staging/physionet_grabmyo_semg_i16/build.sh
bash staging/physionet_grabmyo_semg_i16/verify.sh
```

### `download.sh`

1. Fetches `SHA256SUMS.txt`, `LICENSE.txt`, `readme.txt` and
   `MotionSequence.txt`. Each is pinned by SHA-256, and the last three must
   also appear in `SHA256SUMS.txt`.
2. Derives the trial list from `SHA256SUMS.txt`: every
   `Session1/…_trial1.dat|.hea` entry. The list must form the complete
   43 × 17 grid, and the sha256 of its canonical checksum lines is pinned
   (`ad6d952e…`).

   `RECORDS` is not used: it lists every record twice.
3. Fetches the 1,462 files in passes:
   - each pass runs one parallel curl (8 connections, `--retry 10`, stall
     detection with `--speed-limit`/`--speed-time`, no `--max-time`);
   - each file lands as a `.part`, and is promoted only when its SHA-256
     matches `SHA256SUMS.txt`.
4. Parses every header and checks every per-signal WFDB checksum and initial
   value. It pins the aggregate sizes: 479,068,160 B of `.dat` and
   2,273,949 B of `.hea`.

### `build.sh`

Uses only local files. For each trial in (participant, gesture) order:

1. Re-checks both checksums.
2. Parses the header strictly:
   - record line `<name> 32 2048 10240`;
   - every signal is format 16, gain(baseline)/mV, ADC resolution 16,
     ADC zero 0, block size 0;
   - names are exactly `F1-F16, U1, W1-W6, U2, U3, W7-W12, U4`.
3. Decodes the 655,360-byte `.dat`.
4. Checks all 32 initial values and 16-bit checksums.
5. Writes the 28 kept columns frame-interleaved.

Exclusions (none expected): a trial is excluded if any kept channel contains
the WFDB invalid marker -32768 or has fewer than 256 distinct codes, or if
its output is byte-identical to an earlier trial. More than 1% exclusions
fails the build.

### `verify.sh`

`scripts/grabmyo_verify.py` shares no code with the build. It:

1. Re-derives the selection.
2. Parses headers with a whole-line regex.
3. Rebuilds every expected sample by byte-slicing the kept 2-byte cells out
   of each 64-byte source frame.
4. Re-checks the checksums and initial values with `struct`.
5. Re-applies the exclusion rule.
6. Compares every sample byte, every index field (including gains and
   baselines), the exclusion list, stray files, the aggregate output
   SHA-256, the manifest totals and the floors.

Both scripts self-test their decoders on synthetic 32-signal records first,
including corrupted and malformed variants.

## Outputs

- Samples: `.data/samples/physionet_grabmyo_semg_i16/grabmyo_semg_trial_i16/session1_participant<P>_gesture<G>_trial1.bin`.
  Each is int16 LE, shape `[10240, 28]`, time-major.
- Index: `.data/index/physionet_grabmyo_semg_i16/samples.jsonl`. Each row
  carries the standard fields plus:
  - participant, gesture, gesture name, channel names, sample shape;
  - per-channel `adc_gain_per_mv` and `baseline`;
  - min/max, distinct counts;
  - the sample and source SHA-256.
- Stats: `.data/filtered/physionet_grabmyo_semg_i16/ingest_stats.json`. It
  includes exclusions, gain range, channel peak-to-peak in µV (active versus
  Rest), and normalization-extreme counts.
- Logs: `.data/logs/physionet_grabmyo_semg_i16/`

## Realized scope

Figures from the build and verify of 2026-10-05:

- Download: 1,462 record files fetched in a single pass, all matching
  `SHA256SUMS.txt`. The aggregate sizes matched the pins. Total under
  `downloads/`: 485,909,830 B.
- Output: 731 samples covering 43 participants × 17 gestures, with 0
  exclusions.
  - 209,592,320 int16 values in 419,184,640 bytes.
  - Every sample is 286,720 values (10,240 × 28).
  - Aggregate output SHA-256:
    `d70a0eff7a6a6332f5799e3b2163197401ed9ff42c4a577af41cc9e786ff919b`.
- Header comment lines: 0. Kept-channel `-32768` values: 0. Global code
  range: -32767..32766.
- Content: 18,663-46,549 distinct codes per sample (median 38,706).
- Compressibility: the material is close to incompressible for generic
  coders. On 11 evenly spaced samples, zlib-9 reaches 1.03× and xz-6 1.05×.
  This is expected for wide-band, full-range-normalized sEMG.
