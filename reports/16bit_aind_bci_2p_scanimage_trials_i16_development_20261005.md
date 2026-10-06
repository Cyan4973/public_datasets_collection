# AIND BCI two-photon ScanImage trial movies int16 development

## Outcome

Accepted `aind_bci_2p_scanimage_trials_i16`: complete raw in-vivo two-photon calcium-imaging trial movies from the Allen Institute for Neural Dynamics (AIND) Brain Computer Interface (BCI) project.

- Each sample is one ScanImage acquisition file, i.e. one behavioral trial, from one mouse.
- Every frame is emitted as the native int16 PMT digitizer codes ScanImage wrote to disk.

This is the first raw time-lapse laser-scanning microscopy family in the local or downstream corpus. The nearest local families are different material:

- `dandi_001076_zebrafish_calcium_fluorescence_f32`: float32 Suite2p per-ROI traces derived from two-photon movies, not pixels.
- Static 16-bit microscopy and scanner images: BBBC021/039 widefield fluorescence and the GEO GPL5423 ScanArray scans.

## Source and rights

- **Source:** anonymous public S3 bucket `aind-open-data` (us-west-2, versioned), raw `single-plane-ophys_<subject>_<datetime>/pophys/bci_NNNNN.tif` objects.
- **Pinning:** 11 trial TIFFs plus 22 metadata JSONs (`data_description.json`, `session.json`) are pinned in `sources.tsv` by:
  - key and S3 versionId
  - Content-Length
  - multipart ETag (50 MiB parts, recomputed locally)
  - CRC64NVME (recorded only)
  - SHA-256 (computed locally)
- **Download size:** 984,435,006 bytes in total; trial TIFFs alone are 984,250,298 bytes.
- **License:** CC-BY-4.0, from two sources:
  - The AWS Open Data Registry entry `datasets/allen-nd-open-data.yaml` (commit `23f7633f01561373a9426cb02a10b2fc9a528304`) declares `License: CC-BY-4.0` for `arn:aws:s3:::aind-open-data`.
  - Each selected asset's `data_description.json` declares `"license": "CC-BY-4.0"`, `"restrictions": null`, project "Brain Computer Interface", `data_level` raw.
- **Attribution:** AIND; investigators Kayvon Daie and Marton Rozsa.

## Shape and conversion

**Regime.** All 11 trials share one regime, enforced from the ScanImage header and `session.json`:

- rig `442_Bergamo_2p_photostim`
- ScanImage 2023.1, resonant bidirectional scanning, zoom 2
- 512 x 256 px at 58.29007 Hz
- single saved channel 2, int16 at 16-bit ADC, offset subtraction on
- 920 nm excitation at 12% power
- primary motor cortex, 122–150 µm depth

**Exclusions:**

- 38.10 Hz sessions
- a January Green-PMT session
- a 58.27 Hz session
- three subjects whose files interleave channels `[1 2]`
- all 2022–2025 sessions, which use a different setup

**Selection** (deterministic, reproduced by `discover.py`):

- 2026 sessions with at least 20 `bci_NNNNN.tif` files
- skip each session's first and last file
- subjects with at least 3 such sessions (11 of 13)
- per subject, the chronologically first trial of 300–360 frames

Short trials, at roughly the 2nd–3rd percentile of length, were chosen so that 11 distinct mice fit under the 1 GB cap without tiling any natural record.

**Conversion.** A pure-stdlib BigTIFF parser follows the IFD chain. Every page must be:

- 512x256, 16-bit, uncompressed, SampleFormat 2
- stored as one 262,144-byte strip

Per-frame descriptors must show:

- contiguous `frameNumberAcquisition` 1..N
- a constant `acquisitionNumbers` value
- contiguous `frameNumbers` and increasing timestamps
- `endOfAcquisition` only on the last page, whose strip ends at end of file

Strips are copied unchanged, in page order, into one row-major `[frame][scan_line][pixel]` sample. Headers, ROI JSON and descriptors are validation inputs only; no auxiliary series is emitted.

## Accepted output

- Primary samples: 11 (one per mouse)
- Frames: 3,718 (304–358 per trial)
- Primary values: 487,325,696
- Primary bytes: 974,651,392
- Sample size: 79,691,776–93,847,552 bytes; median 44,171,264 values
- Per-sample value distribution:
  - min -1,018 to -99
  - p01 -32 to -8
  - mode 5–28
  - p50 9–220
  - p99 1,656–4,243
  - max 18,591–32,749
  - 6,002–19,169 distinct values
  - negative fraction 2.2–30.3%
  - 0 values at the int16 limits

Caveats:

- Frames within a trial are highly correlated (same FOV at 58 Hz).
- The calcium indicator is recorded only for 4 subjects (GCaMP8s or XCaMP-G).
- The two July subjects had a raw channel-2 dark offset of about +1165 (vs about -600 for the others) before ScanImage subtracted it.
- Rare isolated single-pixel dips to about -1000 occur in 7 trials.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/aind_bci_2p_scanimage_trials_i16` returned PASS with no warnings and the totals above.
- **Verify:** I ran `bash staging/aind_bci_2p_scanimage_trials_i16/verify.sh` myself: `verify_ok samples=11 bytes=974651392` in 28 s. It uses an independent reader, a full frame byte-compare, and source and sample SHA-256 checks.
- **Pins:** the `sources.tsv` SHA-256 and versionId values match `download_record.tsv` for all 33 objects. `build.sh` and `verify.sh` make no network calls.
- **Byte spot-check:** my own minimal IFD walk confirmed:
  - a uniform 264,528-byte page stride in every file
  - byte-identical first, last, and 3 random frames per file vs the samples
- **Frame scan:** a per-frame scan of all 3,718 frames found:
  - stable frame means and no dark frames
  - 0 consecutive duplicate frames, 11/11 distinct first frames
  - odd-value fraction 0.46–0.54, gcd 1 (no lattice)
  - negative excursions below -300 are isolated single pixels
- **Images:** coarse mean images show soma-like structure with edge vignetting and a distinct field of view per mouse.
- **Header diff:** across all 439 ScanImage keys, the following are identical in all 11 files:
  - sampleRate, input range, pixelBinFactor
  - fill fraction, pixel dwell, beam power
  - filter, zoom, channelSave
  - Photostim status 'Offline'

  Only the subtracted channel offsets, LUTs, motion-correction Z bounds and a ±0.04 µs linePhase differ.
- **Rights:** fetched the pinned registry YAML and read the license; inspected a local `data_description.json`. A grep of all scripts found no credentials.
- **Novelty:** `novelty.py --url https://aind-open-data.s3.amazonaws.com/` matched only this staging recipe. Term searches (two-photon, calcium, scanimage, aind, bci, gcamp, suite2p, microscopy, fluorescence, video) found only the DANDI ROI-trace family and the static microscopy and scanner images. Nothing in the downstream corpus is two-photon.
