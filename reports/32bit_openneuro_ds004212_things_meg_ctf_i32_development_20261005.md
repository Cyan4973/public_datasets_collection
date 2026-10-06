# THINGS-MEG CTF-275 axial-gradiometer int32 development

## Outcome

Accepted `openneuro_ds004212_things_meg_ctf_i32`. It contains native signed-int32 SQUID ADC counts from first-order axial gradiometers of the NIH CTF-275 MEG system, taken from the CC0 OpenNeuro THINGS-MEG dataset (ds004212 v3.0.0).

This is the corpus's first magnetoencephalography family at any width, locally or downstream. The nearest families are different modalities: scalp EEG int16 (`eeg_physionet`, `chbmit_physionet`), Open Ephys extracellular int16, and seismic int32 counts downstream.

## Source and rights

- Source: the anonymous, versioned S3 bucket `s3://openneuro.org/ds004212/`. Every object is requested with `?versionId=`.
- License evidence: `dataset_description.json` at versionId `wfsYJNoFXN6rHilyRd9qTP1Uox0FqQcC`. It is 529 B, with MD5 `e1cae4f6b155f8325beb0921809b35c3` and SHA-256 `7be949c4…a2`, and declares `"License": "CC0"` and `DatasetDOI doi:10.18112/openneuro.ds004212.v3.0.0`. download.sh and build.sh both re-check the name, license and DOI.
- Pins: `selection.tsv` pins the S3 key, versionId, size and MD5/ETag of all 24 res4 objects (3,188,345 B each) and all 24 meg4 objects (517,824,008 B each). `streams.tsv` pins each channel block's index, byte range and SHA-256.
- Safety: the data come from human participants. The release is de-identified under NIH IRB 93-M-0170, and the recipe sets `contains_sensitive_data = true`, consistent with the accepted OpenNeuro ds000030 recipes. Samples carry only pseudonymous BIDS labels. The recording dates in the res4 headers stay in the download cache.

## Shape and conversion

- Scope: `sub-BIGMEG1..4` × `ses-01/03/05/07/09/11` × `run-01` of the main task, which gives 24 runs.
- Channels: 8 fixed gradiometers per run, one mirrored L/R pair per region: MLF32/MRF32, MLC32/MRC32, MLT33/MRT33 and MLO32/MRO32.
- Index derivation: each channel is matched on the label before `-1609`, and its index is re-derived from that run's own res4.
- Natural record: one complete channel over one 348-s single-trial run, which is 417,600 values at 1200 Hz.
- Fetch: each channel block `[8 + c·417600·4, +1,670,400)` is fetched with an exact HTTP 206 range. No whole run is downloaded.
- res4 parsing follows the MNE-Python layout: run description at 1844 + rdlen, then the filter table, 32-B names, 1328-B channel records and the 1992-B compensation records. Every run must pass these checks:
  - the compensation table ends exactly at EOF
  - sensor-type counts are {5:272, 1:19, 0:9, 18:8, 17:1, 20:1}
  - all type-5 channels are at grade 3 with qgain 2^20
  - the 310-label order is identical across runs
- Conversion: big-endian int32 is written unchanged as little-endian int32. There is no scaling, offset removal or filtering. proper_gain (constant per channel, |2.80–2.92e9|, sign varies) and qgain are kept as index metadata only.

## Accepted output

- Primary samples: 192 (24 runs × 8 channels)
- Primary values: 80,179,200
- Primary bytes: 320,716,800
- Sample size: 417,600 values (1,670,400 B) each, so the median is 417,600
- Global value range: -1,009,352..893,741, about 21 bits. 91.4894% of values lie outside the int16 range, and 14 of 192 streams fit entirely in int16.
- Per-stream peak-to-peak: 4,553 / 10,354 / 50,564 (min / median / max)
- Per-stream distinct values: 3,684 / 7,291 / 31,977
- Unique 1-s blocks: 66,816 of 66,816; no constant blocks and no int32 saturation
- Download: 397,491,481 B, of which 76,520,280 B is res4 and 320,716,800 B is channel ranges. The upstream main-task total is about 249 GB.
- Aggregate SHA-256 (sample files concatenated in sorted path order): `94da96060efe3f4386a970f80ecaf73c4e4cffdb84b30b550de0ac62d1ac1c70`

## Judge checks

- **Gate:** `tools/autocollect/gate.py` passed with no warnings.
- **verify.sh:** I re-ran it; rc=0, with 192 samples, 80,179,200 values and 320,716,800 bytes verified byte for byte against an independent struct re-conversion.
- **Upstream probe:** I fetched a 4 KB range myself from the pinned meg4 version (sub-BIGMEG3 ses-07 MRT33, channel 271, sample 300,000; HTTP 206). It matched the local LE sample exactly.
- **Independent res4 check:** I located the name slots by searching for the label strings rather than walking offsets. Slot 0 is `SCLK01-177`, and all 192 selected (run, channel) pairs are type 5, grade 3 and qgain 2^20 at the pinned indices. In sub-BIGMEG1 ses-01, rdlen=1, nfilt=0, and ncomp=1388 ends exactly at 3,188,345 B.
- **Bytes:**
  - The first-difference GCD is 1 in every stream, and the low 3 bits are uniform, so nothing is widened onto a lattice.
  - The largest step is 747–8,075 counts, with no flux-jump artifacts.
  - Standard deviation is 493–8,809 counts, and first-difference noise of about 200 counts is physically plausible at about 0.34 fT per count.
  - Within-run channel correlation is ≤ 0.15 on first differences and ≤ 0.74 raw; the same channel across sessions has r=0.11.
- **Rights:** I fetched the pinned `dataset_description.json` myself: CC0, same MD5. The current version is identical. The scripts contain no credentials, and the index has no dates or free text.
- **Novelty:** `novelty.py` matched only this candidate on the source URL and terms. There are no MEG, CTF or gradiometer families locally, in the registry, in the ledger or downstream.
- **Width caveat (accepted):** the upper magnitude comes mostly from per-channel, per-session DC offsets, and within-stream signal is about 13–16 bits. The storage is native CTF int32, and 178 of 192 streams exceed the int16 range, so this is not a hollow 32-bit family.
