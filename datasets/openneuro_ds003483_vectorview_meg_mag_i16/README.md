# OpenNeuro ds003483 Vectorview MEG Magnetometer tSSS Int16 Channel Streams

612 complete signed-int16 magnetometer channel streams from the CC0 OpenNeuro
"Logical reasoning study" (ds003483): all 102 Elekta Neuromag Vectorview
SQ20950N magnetometers (FIFF coil type 3024) of the continuous deduction-task
run of six participants, at 1000 Hz.

## Scope

| run | buffers (= seconds) | leading FIFF skip (buffers) | FIF bytes |
|---|---:|---:|---:|
| sub-027 deduction run-1 | 696 | 11 | 450,600,455 |
| sub-018 deduction run-1 | 700 | 132 | 453,158,419 |
| sub-028 deduction run-1 | 709 | 8 | 458,916,159 |
| sub-024 deduction run-1 | 732 | 82 | 473,639,111 |
| sub-017 deduction run-1 | 771 | 12 | 498,598,595 |
| sub-015 deduction run-1 | 805 | 176 | 520,361,207 |

- 6 runs x 102 magnetometers = 612 samples of 696,000-805,000 values
  (4,413 s of recording in total): 450,126,000 int16 values,
  900,252,000 primary bytes (under the 1 GB cap).
- Download: 2,855,273,946 B of FIF plus a 352 B dataset description. With the
  samples, the footprint is about 3.76 GB, under the driver's 5 GB per-candidate cap.
- Selection rule: the six smallest task-deduction run-1 FIF objects by size.
  This is the largest subject set whose complete magnetometer output fits
  under the 1 GB primary cap. `discover.sh` re-derives `selection.tsv` from
  the bucket listing, HEADs and small byte ranges, and reproduces it exactly.
- The dataset has 21 deduction and 20 induction runs (21 subjects): 26.3 GB
  of FIF holding about 8.4 GB of magnetometer streams. The other 35 runs are
  excluded only because of the cap.

## What the values are

The upstream raw files are **MaxFilter 2.2.10 output**, not unprocessed
acquisitions. Every selected file carries two identical FIFF processing
records created by `maxfilter 2.2.10`, each with:
- SSS_INFO: job 5, FIFFV_SSS_JOB_MOVEC_FIT (head-movement compensation),
  head frame, Lin = 8, Lout = 3, 306 channels
- SSS_ST_INFO: job 10, temporal SSS (tSSS), correlation limit 0.9, 10 s window
- a cross-talk CHANNEL_DECOUPLER (`create_ct_matrix 1.0`)
- an SSS_CAL fine-calibration block

MaxFilter wrote the result back in the vendor's FIFFT_DAU_PACK16 storage
format: big-endian int16 codes with per-channel scale. For every magnetometer
the scale is range 1.9073486e-05 x cal 4.14e-11, about 0.79 fT per code, so
field [T] = code x range x cal, identical across all 612 streams. The emitted
values are these stored int16 codes, unchanged. They are the published
machine-facing representation, but they are not raw SQUID ADC readings.

Acquisition (BIDS sidecars and FIFF measurement info):
- Elekta Neuromag Vectorview, device serial 3058, at CTB-UPM Madrid
- 1000 Hz sampling, online 0.1–330 Hz, 50 Hz mains
- continuous head localisation, with HPI coils at 169/176/183/190 Hz active
  during the runs

The streams are complete: nothing is trimmed, including the first buffers
and every artifact episode.

Realised statistics (index and a 1-in-6 value scan):
- Codes span -18,254..15,965 overall.
- Per stream: median minimum -4,031 and median maximum 3,949; median
  peak-to-peak 7,967 (2,698–33,979).
- Distinct values per stream: 1,937–10,058, median 3,865.
- Longest identical run: 2–4 samples.
- 74.5% of values have |code| > 127, 0.26% have |code| > 2,047, and 0.0005%
  have |code| > 8,191.

The bulk of each stream therefore occupies about 12 bits. The rare large
codes come from brief broadband bursts that recur mid-run, at the same
instant across several channels (for example sub-027 around sample 360,150;
5–38 episodes in the streams inspected). They are kept as recorded. Their
physiological or instrumental cause (movement, muscle, sensor jumps) is not
established.

## Format and conversion

FIFF is a chain of tags, each with a 16-byte big-endian header (kind, type,
size, next) and blocks delimited by 104/105 tags. `scripts/fif_meg.py`:
1. Follows the `next` pointers from offset 0. In these files the chain ends
   (`next = -1`) on a FIFF_NOP (kind 108). The FIFF_DIR directory sits right
   after it, outside the chain, and is reached via FIFF_DIR_POINTER. The chain
   must end exactly where FIFF_DIR starts, FIFF_DIR must end at EOF, and the
   walked tag list must equal the directory entries exactly.
2. Reads NCHAN/SFREQ/DATA_PACK/filters and the 320 FIFF_CH_INFO records
   **only from block 101**. The HPI measurement block 108 carries a decoy
   NCHAN=306 and four 1.2 MB FIFF_EPOCH tags.
3. Selects channels with kind = 1 and coil_type = 3024 in ch_info order
   (indices 2, 5, …, 305). The index is never hard-coded: all 102 must exist
   with the pinned range/cal/unit, and the channel order must match across runs.
4. In FIFFB_RAW_DATA (102), requires one leading FIFF_DATA_SKIP followed only
   by type-16 buffers of 640,000 bytes (1000 samples x 320 channels). A short
   final buffer would be allowed but none occurs.
5. Byte-swaps each buffer to native int16, takes column k of each
   magnetometer, and appends it little-endian to that channel's file:
   `samples/<id>/vectorview_magnetometer_tsss_i16/<sub>_ses-1_task-deduction_run-1_<MEGxxx1>.bin`.

The leading FIFF_DATA_SKIP (8–176) is a start offset. MNE-Python
`_read_raw_file` turns it into `first_samp = skip x 1000`; it is not a gap
and has no samples. It is recorded as `fiff_leading_skip_buffers` /
`fiff_first_sample` in the index. A skip between buffers would be a real
gap and is fatal; none of the six runs has one.

Each index row also carries:
- subject, source key and versionId
- channel name, ch_info index, scan/log numbers, coil type
- range, cal, tesla_per_code
- minimum, maximum, distinct values, longest identical run
- sha256

`filtered/<id>/ingest_stats.json` summarises totals and per-run buffer counts,
leading skips and SSS NFREE values (data-dependent, 67–71).

## Excluded

The following are excluded:
- The 204 coil-3012 planar gradiometers: unit T/m, cal 3.25e-9, a separate
  scale and regime.
- EOG061, ECG062, STI101/201/301 and CHPI001-009.
- All header content: subject block 106 (pseudonymous names, birth date, sex,
  handedness), measurement date, file IDs, digitisation, HPI fits, processing
  history payloads.
- The other 35 runs.
- The `derivatives/pipeline_preprocessing` epochs.

## Integrity

`download.sh`:
- Checks the pinned dataset description (MD5, License = CC0, DOI v1.0.2).
- Fetches each FIF with resumable curl (`-C -`, stall-based
  `--speed-limit/--speed-time`, no `--max-time`) at its pinned versionId.
- Requires the pinned size and MD5 (the S3 objects have single-part ETags).
- Runs `check-fif` before renaming `.part` to `.fif`. This covers the full
  structural validation above, the pinned FIFF_DIR offset, buffer count and
  leading skip, the processing-history signature, and non-constant
  magnetometer columns in the first, middle and last buffers.

`build.sh`:
- Repeats the MD5 and structural checks.
- Rejects any stream with fewer than 1000 distinct values, peak-to-peak under
  1000 codes, a flat run over 100 samples, a constant 1-s block, an
  int16-extreme value, or a duplicate payload or 1-s block.

`verify.sh` (`scripts/verify_streams.py`) shares no code with build:
- Navigates each file through FIFF_DIR rather than the tag chain.
- Checks every tag header against its directory entry: entries must be
  contiguous, and every tag has `next = 0` except the final FIFF_NOP (`-1`).
- Re-derives the channel table, magnetometer set, processing-history
  signature and buffer layout.
- Re-converts every buffer with `struct` and compares byte-for-byte with each
  sample.
- Recomputes all index statistics.
- Applies the same degeneracy policy.
- Checks manifest `sample_count`/`total_size_bytes`, the ingest stats and the
  on-disk file set.

Both parsers were self-tested on synthetic FIF files (short final buffer,
inner-skip, wrong-type, directory-corruption and history cases) and on
real-byte files spliced from range-fetched heads of all six runs.

## Run

```bash
bash staging/openneuro_ds003483_vectorview_meg_mag_i16/download.sh   # 2.86 GB
bash staging/openneuro_ds003483_vectorview_meg_mag_i16/build.sh
bash staging/openneuro_ds003483_vectorview_meg_mag_i16/verify.sh
```

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/openneuro_ds003483_vectorview_meg_mag_i16/`.

## License and safety

`dataset_description.json` (versionId `5n.o11Crl3Nvg7AKgzfAfroeS016CLTf`)
declares `"License": "CC0"` and `"DatasetDOI": "10.18112/openneuro.ds003483.v1.0.2"`.
The data come from the official anonymous OpenNeuro S3 bucket.

This is de-identified human MEG. Only anonymous magnetometer code streams
keyed by BIDS pseudonymous subject labels are emitted. The FIF files, whose
subject block holds pseudonymous names and a birth date, stay in the local
download cache, and the parser never decodes that block.

Novelty: this is the first MEG family at 16-bit, locally or downstream. The
only other MEG in the corpus is `openneuro_ds004212_things_meg_ctf_i32`, a
different system (CTF-275 axial gradiometers, raw int32 ADC counts), dataset,
site and width. The nearest 16-bit relatives are scalp-EEG families
(`eeg_physionet`, `chbmit_physionet`), which record electrical potentials
rather than magnetic fields.
