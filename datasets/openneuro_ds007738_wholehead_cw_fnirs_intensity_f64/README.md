# OpenNeuro ds007738 Whole-Head CW-fNIRS: resting-state raw intensity (float64)

Raw continuous-wave functional near-infrared spectroscopy (fNIRS) intensity
from the OpenNeuro dataset
[ds007738 "Whole-Head Cocktail Party fNIRS", snapshot 1.0.0](https://openneuro.org/datasets/ds007738/versions/1.0.0)
(Boston University, Boas / Yücel / Sen labs; DOI
10.18112/openneuro.ds007738.v1.0.0; CC0). Device: whole-head high-density CW
fNIRS, 56 sources x 144 detectors, 1134 source-detector-wavelength channels at
760 and 850 nm, ~8.99 Hz.

## What is collected

- One primary series, `cw_fnirs_raw_intensity_f64`. One sample is the complete
  stored `/nirs/data1/dataTimeSeries` matrix of one resting-state run (5+
  minutes of central fixation without a task), copied byte for byte as
  little-endian float64. Order is the stored row-major order: time-major, so
  all 1134 channels of frame 0 come first, then frame 1, and so on. Shape
  is T x 1134 with T ≈ 2,850-3,210 (the index records `sample_shape`).
- Every `measurementList*/dataType` must be 1 (SNIRF "CW amplitude", i.e. raw
  intensity, not optical density or haemoglobin). The channel table
  (sourceIndex, detectorIndex, wavelengthIndex, dataType, dataTypeIndex for
  channels 1..1134) must hash to the pinned
  `d8099a28416f150446e432cbe1363c73b9cca2abfdafe9e15f9fb1a8d3eaf987` in every
  run, so channel k means the same optode pair and wavelength in every sample.
  Any run whose channel order differs is rejected.
- Scope: all 24 resting-state SNIRF runs of the snapshot, one per subject
  (sub-01..05, 10, 11, 13, 14, 15, 18, 20, 22, 23, 24, 25, 28, 29, 32, 33, 35,
  41, 44, 46). sub-12 has a resting `events.tsv` but no resting SNIRF, and the
  other 13 participants have no resting run.
- Realized output: 24 samples, 80,828,118 values, 646,624,944 bytes. T ranges
  from 2,832 to 3,207 frames (25.7-29.1 MB per sample; median 3,344,733
  values). The aggregate SHA-256 over the sample hashes in index order is
  `a508327917aaa7ed0e751ce785b000461e759c60acc4274aa9da73df5315e68a`.
  `runs.tsv` pins every run's data offset, byte count, time points and
  range SHA-256; download, build and verify all enforce these.
- Not collected: the 199 task runs (overt, covert, visualorient,
  longvisualorient/videoattend), which could only form separate families; the
  time vector; aux eye-tracking channels; stim; probe geometry; metaDataTags;
  and every other OpenNeuro fNIRS dataset. Their devices and export precision
  differ: for example, the NIRx-derived ds008192 and ds006377 store values
  rounded to 8-10 decimals.

## Material properties (realized build; read this)

- Range 0 to 0.939 in arbitrary instrument units, spanning about six decades,
  with no negative values. The instrument writes a 1e-6 floor for dark or
  saturated channels. Over all 24 runs, 3.02% of values are exactly 1e-6 and
  0.037% are exactly 0. A small share of positive values fall below 1e-6
  (0.17% in sub-01). The floor share varies widely between subjects (optode
  coupling): from 0.18% (sub-14) to 15.4% (sub-04) and 10.1% (sub-23), with a
  median of about 1.7%. Exact zeros run from 0.0003% to 0.13% per run. verify
  prints the floor, zero and NaN shares for every run and in total.
- First-frame NaN: in the 13 runs from sub-20 onward, most channels of frame
  0 hold the quiet NaN 0xFFF8000000000000 (sign bit set, as numpy writes it):
  908-1,063 of 1,134 values, and frame 0 only. The 11 runs sub-01 to sub-18
  have none. This looks like an acquisition or export software difference
  between sessions. The device, channel layout, unit and value statistics
  are otherwise the same, and the NaNs make up 0.026-0.032% of a run (0.016%
  overall). They are kept as stored, not trimmed. Any other NaN payload, ±Inf,
  or more than 0.5% NaN is fatal.
- Constant channels (a channel stuck at one value for the whole run): 0 to
  13 per run out of 1134. They occur only in sub-01 to sub-18, and verify
  rejects a run with more than 283.
- Width disclosure: within one channel the values act like integer-like
  mantissas of at most 24 bits times one float64 per-channel scale. The
  ratio/LCM test (`scripts/scale_test.py`, the same test as the accepted IBL
  amplitude recipe) passes for 57-99% of the testable channels per run (for
  example 967 of 1,131 in sub-01, 1,120 of 1,134 in sub-14 and 646 of 1,129
  in sub-04). The per-run median LCM is 11-21 bits, while a generic float64
  control gives LCMs of hundreds of bits. So this is not 53-bit-entropy data,
  but only the exact zeros are float32-exact, and the matrix cannot be
  narrowed to float32 unless the per-channel scales are also stored. The
  index records the test for every sample.
- Distinct values per run: 30% (sub-04) to 70% (sub-28), median about 56%.
  The floor and the per-channel quantisation repeat values. Runs with many
  floor values have the fewest distinct values.

## Access and decode

The 24 SNIRF files total 2.39 GB, mostly eye-tracking aux data. The recipe
fetches only what it needs, as anonymous HTTP byte ranges of
`https://s3.amazonaws.com/openneuro.org/ds007738/...`. Each 206 response must
carry `Content-Range: bytes a-b/<pinned size>` and the pinned S3 ETag, so
every range provably comes from the pinned object.

1. `download.sh` fetches `dataset_description.json` and checks License `CC0`,
   DatasetDOI and Name. It also fetches `CHANGES` (snapshot `1.0.0
   2026-05-01`), `README.txt` and `participants.tsv`, plus the complete S3
   ListObjectsV2 listing of `ds007738/`, paginated by continuation token (1,023
   keys, 2 pages). The set of `*_task-resting_run-01_nirs.snirf` keys must
   equal `runs.tsv` exactly, with every size and ETag matching.
2. HDF5 metadata: `scripts/snirf_fnirs.py meta-plan` walks superblock v0 →
   root → `/nirs` → `/nirs/data1` (exactly `dataTimeSeries`, `time`,
   `measurementList1..1134`) → the dataset header → all 1134 measurementList
   groups → `/nirs/probe/wavelengths`. It reads over a sparse cache of aligned
   1 MiB blocks, and each round fetches the next missing block of every run.
   On the live files this took 8-10 blocks per run (8-10 MiB) in 8-10 rounds.
   The dataset address and size come from the object header, never a
   hard-coded offset. The reader requires a contiguous, unfiltered
   `H5T_IEEE_F64LE` dataset of shape (T ≥ 1000, 1134) whose size equals
   T·1134·8, a time vector of length T, SNIRF formatVersion 1.0, wavelengths
   (760, 850), all dataType = 1 and the pinned channel-table hash.
3. Data: one exact range per run for `dataTimeSeries` (about 26.7-29.2 MB).
   `curl` cannot combine `--continue-at` with `--range`, so `fetch_range`
   resumes by hand: bytes already in `<file>.part` are kept and the next
   request asks for the remainder. Transfers are bounded by
   `--speed-limit 1024 --speed-time 120`, never by `--max-time`.
4. `inventory` re-validates every range: size, the missing-value policy,
   non-constancy, at least 20% distinct values, and any `data_sha256` pin in
   `runs.tsv`. A semantically invalid range is deleted so that a re-run
   fetches it again. It writes the SHA-256 of every fetched range (data and
   metadata blocks) to `range_sha256.tsv`.

Realized download: 887,208,565 bytes in 50 s. That is 646,624,944 bytes of
data ranges plus 8-10 metadata blocks of 1 MiB per run, with small metadata
files making up the rest. Every data offset resolved to 13056, but it is
read from the header, not assumed. The first attempt failed when
inventory rejected sub-20 because the pinned NaN pattern was wrong (I had
misread the byte order of 0xFFF8...). The pattern was corrected and the
re-run resumed.

`scripts/nwb_hdf5.py` is the strict standard-library HDF5 subset reader from
the accepted `dandi_ibl_bwm_spike_amplitudes_f64` recipe, unchanged in code.
The SNIRF files (h5py-written, superblock v0, symbol-table groups) parse with
it as is.

## Validation

- `scripts/selftest.py` writes a synthetic SNIRF-like HDF5 file byte by byte.
  It contains a vlen formatVersion string in a global heap, a two-level
  data1 group B-tree, a continuation block, a contiguous f64 matrix with a
  partly NaN first frame, measurementList groups of scalar int64, a
  wavelengths vector, and ignored aux/metaDataTags groups. The real
  `read_layout` must recover the data range bit for bit and report
  `MissingBlock` for an absent block. It must reject these cases: dataType 2,
  float32 dtype, a filter, a wrong channel count, a size mismatch, swapped
  channel order, an extra data2 group, wrong wavelengths, a missing
  measurementList, formatVersion 1.1, bad EOF and bad signature.
  `payload_stats` must reject non-canonical NaN, Inf, too many NaN, a
  constant matrix, low distinctness and a short payload. download.sh,
  build.sh and verify.sh all run the self-test first.
- `build.sh` re-resolves every layout from the cached blocks. It checks the
  blocks and data ranges against `range_sha256.tsv`, applies the policy, and
  writes the samples, `samples.jsonl` and `ingest_stats.json`. Each index
  row holds the subject, source key/ETag/offset, shape, layout hash, NaN/zero/
  floor/below-floor/negative counts, finite min/max/mean, distinct count,
  float32-exact count, the scale-test summary and the SHA-256.
- `verify.sh` (`scripts/verify_fnirs.py`) re-walks the metadata by HDF5 path
  resolution, not the builder's `read_layout`. It re-checks every dataType and
  the channel table, byte-compares every sample with its fetched range,
  recomputes the statistics through separate memoryview/array code, and
  applies the same policy. It rejects duplicate samples, constant samples,
  samples under 20% distinct, and samples with more than 283 constant
  channels. It checks the manifest totals and `ingest_stats.json`, rejects
  stray files, and prints the NaN, zero and floor shares.
- The whole pipeline (listing, meta-plan, resumed data range, inventory,
  build, verify) ran end to end on sub-01 during authoring, using a one-run
  harness under /tmp.

## Running

```bash
bash staging/openneuro_ds007738_wholehead_cw_fnirs_intensity_f64/download.sh   # ~887 MB of ranges
bash staging/openneuro_ds007738_wholehead_cw_fnirs_intensity_f64/build.sh
bash staging/openneuro_ds007738_wholehead_cw_fnirs_intensity_f64/verify.sh
```

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/openneuro_ds007738_wholehead_cw_fnirs_intensity_f64/`.

## Caveats

- 24 samples is the whole natural resting population of the snapshot. Each
  sample is large (about 27 MB).
- Novelty: no fNIRS, SNIRF or diffuse-optical material exists in the local
  corpus, the registry, the ledger or the downstream mirror (`novelty.py`).
  The nearest OpenNeuro families are other modalities: fMRI BOLD, T1w,
  cortical thickness, DTI, MEG (two) and EEG.
- Two acquisition/export variants (with and without the first-frame NaN) are
  documented above rather than split, because the device, channel layout and
  quantity are identical.
