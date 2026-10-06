# THINGS-MEG CTF-275 Axial-Gradiometer Raw Int32 Channel Streams

Native signed-int32 SQUID ADC counts from first-order axial gradiometers of the
NIH CTF-275 MEG system. They come from the CC0 OpenNeuro dataset **ds004212
(THINGS-MEG, v3.0.0)**, recorded while participants viewed THINGS object images.

## Scope

- 4 participants (`sub-BIGMEG1..4`) x 6 sessions (`ses-01, 03, 05, 07, 09, 11`)
  x `run-01` of the main task = 24 runs (`selection.tsv`).
- 8 fixed gradiometers per run, one mirrored left/right pair per CTF sensor
  region: `MLF32 MRF32` (frontal), `MLC32 MRC32` (central), `MLT33 MRT33`
  (temporal), `MLO32 MRO32` (occipital).
- One sample = one complete channel over one run: 417,600 int32 values
  (348 s at 1200 Hz), 1,670,400 bytes.
- 192 samples, 80,179,200 values, 320,716,800 primary bytes.

The upstream has 480 main-task runs of 310 channels each (about 249 GB). This
recipe takes a bounded subset spread across all participants and sessions,
and fetches only the needed channel blocks with HTTP range requests. It never
downloads a whole 518 MB `.meg4` run. Expected download is about 397 MB: 24
res4 headers of 3.19 MB each plus 192 channel blocks of 1.67 MB each.

## Format and conversion

A CTF `.ds` run holds a big-endian `res4` header and a `meg4` data file
(magic `MEG41CP\0`). The `meg4` data is trial-major and channel-major
big-endian int32. Every THINGS-MEG main run is a single trial, so channel `c`
occupies bytes `[8 + c*nsamp*4, 8 + (c+1)*nsamp*4)`.

`scripts/ctf_meg.py` parses `res4` following MNE-Python's
`mne/io/ctf/res4.py`. The run description (`rdlen` at byte 1836) starts at
byte 1844. It is followed by the filter table, the 32-byte channel names, the
1328-byte channel records and the compensation table. The channel-name offset
is therefore derived per file, not hard-coded. Every run must pass these
checks:

- the compensation table ends exactly at EOF
- `nsamp = 417600`, `nchan = 310`, 1200 Hz, 1 trial
- the sensor-type counts are `{5:272, 1:19, 0:9, 18:8, 17:1, 20:1}`
- all 272 type-5 channels have `grad_order_no = 3` (third-order synthetic
  gradiometer) and `qgain = 2^20`
- the 310-label channel order is identical in every run

Channels are matched on the label before the `-1609` serial suffix, and their
index is re-derived from each run's own `res4`.

Each block is decoded as big-endian int32 and written unchanged as
little-endian int32. There is no scaling, offset removal, filtering or
compensation change. `proper_gain` and `qgain` are kept as index metadata
only (tesla = counts / (proper_gain x qgain)).

Values carry large per-channel, per-session DC offsets. Realized values span
-1,009,352..893,741 (about 21 bits), and 91.5% of all values lie outside the
int16 range. Within a stream, peak-to-peak spans 4,553-50,564 counts
(median 10,354), with 3,684-31,977 distinct values per stream (median 7,291).
14 of the 192 streams sit near zero and fit entirely in int16; the family as
a whole does not. zlib level 6 compresses a sample to about 0.43-0.50 of its
size, partly because the top byte is mostly sign extension.

## Excluded

Reference magnetometers and gradiometers (types 0/1), UADC channels,
the SCLK01 sample clock, the UPPT001 trigger, the `hz`/`hz2`
head-localisation datasets, eye-tracking, events, MRI, and all participant
metadata. These runs contain no EEG/EOG or HLC channels.

## Integrity

`selection.tsv` pins the S3 key, `versionId`, size and MD5/ETag of every
`res4` and `meg4` object. `streams.tsv` pins each block's channel index and
byte range, and its SHA-256 once the first acquisition has been audited. To
write the hashes, run `python3 scripts/ctf_meg.py audit ... --write-streams
streams.tsv`. `build.sh` refuses to run until every hash is pinned.
`download.sh` performs these checks:

- the `dataset_description.json` version still says `License: CC0` with the
  v3.0.0 DOI
- each `res4` MD5 matches its pin
- each `meg4` still reports its pinned size and ETag and starts with
  `MEG41CP\0`
- each range returns HTTP 206 with the exact byte count

Streams with constant 1-s blocks, flat runs longer than 120 samples, fewer
than 1000 distinct values, int32-extreme values or duplicate payloads are
rejected. `verify.sh` (`scripts/verify_streams.py`) shares no code with the
builder. It re-walks every `res4`, re-converts every block with `struct`, and
compares the result byte for byte with the samples, the index, the ingest
statistics and the manifest.

## Run

```bash
bash staging/openneuro_ds004212_things_meg_ctf_i32/download.sh
bash staging/openneuro_ds004212_things_meg_ctf_i32/build.sh
bash staging/openneuro_ds004212_things_meg_ctf_i32/verify.sh
```

## License and safety

The license is CC0 1.0, from `dataset_description.json` (`"License": "CC0"`).
Please cite Hebart et al. (2023), eLife 12:e82580, and
doi:10.18112/openneuro.ds004212.v3.0.0.

The source is human-participant data, released de-identified under NIH IRB
protocol 93-M-0170. Samples contain only anonymous sensor count streams keyed
by BIDS pseudonymous labels. Recording dates in the `res4` headers stay in the
local download cache.
