# AIND BCI two-photon ScanImage trial movies — int16

Raw in-vivo two-photon calcium-imaging movies from the Allen Institute for
Neural Dynamics (AIND) Brain Computer Interface (BCI) project. Each sample is
one complete behavioral-trial acquisition: every frame ScanImage wrote for
that trial, as the native int16 PMT digitizer codes it stored on disk.

- Source: anonymous public bucket `s3://aind-open-data` (HTTPS), raw
  `single-plane-ophys_<subject>_<datetime>/pophys/bci_NNNNN.tif` objects.
- License: CC-BY-4.0, from the AWS Open Data Registry entry for the bucket
  (`allen-nd-open-data.yaml`, commit `23f7633f`) and from each selected
  asset's `data_description.json` (`"license": "CC-BY-4.0"`,
  `"restrictions": null`, project "Brain Computer Interface"). download.sh
  re-checks the license on every run.
- Output: 11 samples (one per mouse), 3,718 frames, 487,325,696 int16 values,
  974,651,392 bytes, shape `frames x 256 x 512`, little-endian.

## Material and regime

All selected trials come from one instrument configuration:

| property | value |
| --- | --- |
| rig | `442_Bergamo_2p_photostim` (session.json `rig_id`) |
| software | ScanImage 2023.1, resonant scanning, bidirectional, zoom 2 |
| frame | 512 pixels x 256 lines, 1.953 um/pixel, 58.29007 frames/s |
| channel | single saved channel 2 (`channelSave = 2`, `channelsActive = 2`), "Red PMT" detector in session.json |
| data type | `channelsDataType = 'int16'`, 16-bit ADC, `channelsSubtractOffsets` on |
| excitation | 920 nm, 12% power; primary motor cortex, 122-150 um depth |

The values are offset-subtracted PMT codes. ScanImage measures each channel's
dark level at acquisition start and subtracts it, so the background mode sits
near zero, small negative values are shot/electronic noise, and bright
GCaMP-type cell bodies form a long positive tail. Across the complete built
trials (`filtered/<id>/build_stats.json`): mode 5..28, median 9..220, p01
-8..-32, p99 1.6k..4.2k, max 18.6k..32.7k (rare bright transients), and
negative-value fraction 2-30%. No value reaches the int16 limits. Six trials
contain rare negative excursions down to about -1000, far below their p01.
Distinct values per trial range from 6,002 to 19,169. The raw dark offset that
was subtracted differs by session (channel 2: about -600 for most, about +1165
for the two July 2026 subjects). After subtraction the distributions fall in
the same range, and the index records the subtracted offset per sample.

The calcium indicator is transgenic GCaMP8s (Ai237: subjects 820614, 820615)
or XCaMP-G (Ai230: 824946, 855519). For the 7 Cas9-line subjects (849680,
850378, 850381, 857094, 857095, 857096, 857098) the AIND procedures metadata
does not record the indicator. All 11 subjects use the same imaging
configuration and the same digitizer path.

## Selection (resolved 2026-10-05, pinned in `sources.tsv`)

1. Sessions: the 2026 `single-plane-ophys` BCI sessions on rig
   `442_Bergamo_2p_photostim` whose `tiff_stem:bci` stream is 512x256 at
   58.29007 Hz with a single Red PMT. Excluded: the 38.10 Hz sessions of
   2026-05-15, the January 2026 Green-PMT session of 820615, a 58.27 Hz
   session of 823755, and subjects 843574, 865606, and 865607, whose
   ScanImage files save channels `[1 2]` (interleaved two-channel pages). Test
   subject 123456 is also excluded. Older sessions (2022-2025: 800x800
   @ 19.4 Hz, or ScanImage 2022 with a different channel and offsets) are a
   different regime and are not mixed in.
2. Trial files: only `bci_NNNNN.tif`. spont*, stack, and photostim files are
   never used. Sessions need at least 20 trial files. Each session's
   first acquisition and its final acquisition are skipped; the final file is
   usually a truncated 4-60 MB tail cut off when the session stopped.
3. Subjects: subjects with at least 3 such sessions (11 of the 13 eligible).
   One trial per subject keeps each sample an independent field of view.
4. Trial: per subject, the chronologically first remaining trial whose length
   is 300-360 frames (5.1-6.2 s).

Why short trials: typical trials run 450-800 frames (median about 670 frames,
about 175 MB), and natural records are never tiled. At typical length the
1,000,000,000-byte cap would admit only about 5 mice. Taking trials at
roughly the 2nd-3rd percentile of length fits 11 mice (11 distinct fields of
view) under the cap. The window starts at 300 frames to stay clear of the
rare shorter outliers. Trial length is a behavioral variable (time to reach
the BCI target). It does not change what each frame measures.

Each pinned object is identified by key plus S3 `versionId` (the bucket is
versioned and grows weekly), Content-Length, the multipart S3 ETag (50 MiB
parts, recomputed locally), and the S3 full-object CRC64NVME (recorded for
reference). SHA-256 is computed locally and written to
`downloads/<id>/download_record.tsv`.

## Conversion

`scripts/aind_bci.py` (pure standard library):

- checks the BigTIFF header (`II`, version 43) and the ScanImage static header
  (magic 117637889, version 4), parses the SI text, and requires the regime
  settings above (`EXPECTED_SI`, frame rate, channel-2 offset subtraction);
  the ROI JSON (about 40 KB) must parse
- follows the IFD chain from the header's first-IFD offset (no fixed-stride
  assumption); every page must be 512x256, 16-bit, uncompressed,
  BlackIsZero, SampleFormat 2, with one 262,144-byte strip
- checks each page's ScanImage frame descriptor: contiguous
  `frameNumberAcquisition` 1..N, one constant `acquisitionNumbers` value
  (ScanImage's acquisition counter; it can differ from the `_NNNNN` file
  index, e.g. 820614 `bci_00011.tif` is acquisition 9, and the index records
  both), contiguous `frameNumbers`, increasing timestamps, and
  `endOfAcquisition = 1` only on the last page, whose strip must end exactly
  at end of file
- copies each page's strip (already little-endian int16) in page order into
  `samples/<id>/bci_2p_trial_movie_i16/<subject>_<datetime>_bci_<acq>.i16`

Per-frame descriptors, the header, and the ROI JSON are validation inputs
only. Nothing auxiliary is emitted.

`scripts/verify_trials.py` does not import the build module. It re-walks every
TIFF with its own tag reader, byte-compares every frame with the sample,
re-checks the sample SHA-256 and the index min/max/distinct values, and
rejects constant frames, samples with fewer than 256 distinct values, samples
whose range does not straddle zero (that is, not offset-subtracted), a
manifest/index mismatch, or output over 1 GB.

## Running

```bash
bash staging/aind_bci_2p_scanimage_trials_i16/download.sh   # ~984 MB, resumable
bash staging/aind_bci_2p_scanimage_trials_i16/build.sh
bash staging/aind_bci_2p_scanimage_trials_i16/verify.sh
```

All scripts honor `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/aind_bci_2p_scanimage_trials_i16/`. The build runs the
synthetic parser self-test (`aind_bci.py selftest`) first.

`discover.sh` is optional. It fetches only metadata: the 2026 session
listings, each `session.json`, and each pophys listing. It re-applies the
selection rule through `scripts/discover.py` and reports whether the result
still matches `sources.tsv`. The pins stay authoritative, and download.sh never
discovers keys.

The trial TIFFs' SHA-256 values are not published upstream. They were
computed on the first download (2026-10-05, `download_record.tsv`) and are now
pinned in `sources.tsv`. download.sh, build.sh, and verify.sh enforce them in
addition to the versionId, size, and multipart ETag.

## Novelty and caveats

- New modality for the corpus: raw time-lapse laser-scanning fluorescence
  microscopy of living tissue. The nearest local families are
  `dandi_001076_zebrafish_calcium_fluorescence_f32` (Suite2p ROI traces
  extracted from two-photon movies, float32, not pixels), the static 16-bit
  microscopy/scanner images (BBBC widefield TIFFs, the GEO ScanArray
  microarray scans), and `openneuro_ds000030_fmri_bold_i16` (a neuroimaging
  time series, but MRI).
- Only 11 samples. Each natural record is 80-95 MB here, so the 1 GB cap
  bounds the count. Records are not split.
- The 11 trials are short trials (fast BCI trials), chosen for the cap as
  explained above.
- Frames within one trial are highly correlated (same field of view at 58 Hz).
  That is the nature of the material.
