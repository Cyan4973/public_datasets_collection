# OpenNeuro ds003483 Vectorview MEG magnetometer int16 development

## Outcome

Accepted `openneuro_ds003483_vectorview_meg_mag_i16`. Each sample is the complete native signed-int16 stream of one Elekta Neuromag Vectorview magnetometer (FIFF coil type 3024) over one continuous run. The source is the CC0 OpenNeuro "Logical reasoning study" (ds003483 v1.0.2).

**What the values are:**
- The values are the stored FIFFT_DAU_PACK16 codes of the published FIF raw files, which are MaxFilter 2.2.10 output: temporal SSS with a 0.9 correlation limit and 10 s window, head-movement compensation, cross-talk correction and fine calibration.
- They are therefore not unprocessed ADC readings. They are the dataset's own machine-facing representation, copied unchanged apart from a big- to little-endian byte swap.
- The manifest and README state this caveat explicitly.

**Novelty:**
- This is the first MEG family at 16-bit, locally or downstream.
- MEG already exists locally at 32-bit as `openneuro_ds004212_things_meg_ctf_i32`, a different system, sensor type, site and width (raw CTF-275 axial-gradiometer int32). The novelty kind is therefore `new_source`, not `new_modality`.
- The nearest 16-bit relatives are scalp EEG (`eeg_physionet`, `chbmit_physionet`) and the PCG, EHG and sEMG families accepted in this effort, all different modalities.

## Source and rights

- **Source:** the anonymous, versioned S3 bucket `s3://openneuro.org/ds003483/`. Every object is requested with `?versionId=`.
- **License evidence:** `dataset_description.json` at versionId `5n.o11Crl3Nvg7AKgzfAfroeS016CLTf`:
  - 352 B, MD5 `2672ea7a59f7aff3183edb230044d904`, SHA-256 `ba2b5e8c…784b`
  - declares `"License": "CC0"` and `"DatasetDOI": "10.18112/openneuro.ds003483.v1.0.2"`
  - download.sh and build.sh both re-check the name, license and DOI.
- **Pins:** `selection.tsv` pins the key, versionId, size, MD5 (equal to the single-part ETag), FIFF_DIR offset, buffer count and leading skip of six FIF objects, totalling 2,855,273,946 B.
- **Version note:** all objects date from 2021-01-24. CHANGES lists 1.0.1 while the DOI says v1.0.2; the versionId pins make this immaterial.
- **Safety:** de-identified human MEG, with `contains_sensitive_data = true`, consistent with the accepted OpenNeuro ds004212, ds004584 and ds000030 recipes.
  - Samples and index carry only BIDS pseudonymous labels (sub-015..028), channel metadata and statistics.
  - The FIFF subject block, measurement date, digitisation, HPI fits and non-magnetometer channels are never decoded or emitted.

## Shape and conversion

- **Scope:** the task-deduction run-1 of the six smallest deduction FIF objects: sub-027, 018, 028, 024, 017 and 015 (696, 700, 709, 732, 771 and 805 s).
  - The full population is 41 runs (21 deduction, 20 induction), about 26 GB of FIF holding about 8.4 GB of magnetometer streams.
  - FIFF buffers are time-major across all 320 channels, so whole files must be fetched. The bound is set by the per-candidate download cap and the 1 GB primary cap.
- **Natural record:** one complete magnetometer channel over one run, 696,000–805,000 values at 1000 Hz.
- **Parsing** (`scripts/fif_meg.py`, pure stdlib):
  - The tag chain is walked from offset 0. It must end on a FIFF_NOP immediately before FIFF_DIR, and must equal the trailing directory entry for entry.
  - NCHAN, SFREQ, DATA_PACK, the filters and the 320 FIFF_CH_INFO records are read only from block 101; the decoy NCHAN=306 in the HPI block is ignored.
  - Magnetometers are selected by kind=1 and coil=3024 in ch_info order (indices 2, 5, …, 305), with pinned range, cal and unit and identical channel order across runs.
  - Two identical `maxfilter 2.2.10` processing records are asserted per file: SSS job 5, Lin 8 / Lout 3; tSSS job 10 with correlation 0.9 over 10 s; `create_ct_matrix 1.0`; SSS_CAL.
- **Raw block:** each raw block holds one leading FIFF_DATA_SKIP (8–176 buffers), which is a start offset as in MNE `_read_raw_file`. It is recorded in the index. An inner skip would be fatal; none occurs.
- **Conversion:** each 640,000-B buffer is byte-swapped, column k of each magnetometer is taken and written as little-endian int16. There is no scaling, offset removal or filtering.
- **Scale:** range 1.9073486e-05 × cal 4.14e-11, about 0.79 fT per code, identical for all streams. The scale is kept as index metadata only.
- **Excluded:** the 204 gradiometers (T/m, different scale), EOG061, ECG062, STI101/201/301 and CHPI001–009.

## Accepted output

- Primary samples: 612 (6 runs × 102 magnetometers)
- Primary values: 450,126,000
- Primary bytes: 900,252,000
- Sample size: 696,000 / 720,500 / 805,000 values (min / median / max)
- Global value range: −18,254..15,965, with no int16 saturation
- Per-stream minimum and maximum: median −4,031 / 3,949 (median_high)
- Per-stream peak-to-peak: 2,698 / 7,967 / 33,979 (min / median_high / max)
- Per-stream distinct values: 1,937 / 3,865 / 10,058
- Longest identical run: 2–4 samples in every stream
- Unique 1-s blocks: 450,126 of 450,126, with no constant blocks
- Download: 2,855,273,946 B of FIF plus 352 B, an extraction ratio of 31.5%
- Aggregate SHA-256 (sample files concatenated in sorted path order): `ce17e6dd6de981b62c5a380ad227de87422248987aa978706ddb9faafe283c1a`

## Judge checks

- **Gate:** `tools/autocollect/gate.py` passed with no warnings: values=450126000, bytes=900252000, samples=612, median 720500, widths [16].
- **verify.sh:** I re-ran it; rc=0 in 1:55. The independent reader navigates via FIFF_DIR and re-converts every buffer with `struct`. It matched all 612 samples byte for byte, re-checked every index field, the ingest stats and the manifest counts, and found 450,126 unique 1-s blocks.
- **Upstream probe:** I computed the position of buffer 500, row 777 of sub-015 from the local FIFF_DIR. A 640-B HTTP 206 range from the pinned versionId `f9836sFjDZp358TQ7fA55Vl4sX0bbcsD` matched all 102 local magnetometer values at sample 500,777 exactly.
- **Bytes:**
  - Across 12 streams from 3 subjects: lag-1 autocorrelation 0.75–0.95, which confirms the row-major de-interleave.
  - The low 2 bits are uniform, and all 2001 codes in −1000..1000 occur in MEG0111 of sub-027, so nothing is widened onto a lattice.
  - The largest first difference is 22,308, with no int16 wrap.
  - Goertzel probes show broadband, low-frequency-dominated MEG with negligible HPI and 50 Hz lines.
  - In the burstiest stream (sub-018 MEG2411), only 17 of 700 seconds exceed three times the median per-second RMS.
  - Within-run pairwise |r| has median 0.13–0.47; the maximum of 0.99 occurs only for adjacent sensors.
- **Width:** a 1-in-12 scan (51 streams, 37.5M values) gives 74.09% above |127|, 0.268% above |2047| and 0.00064% above |8191|. That is about 12 effective bits, stored at the native int16 width.
- **Rights:** I fetched the pinned `dataset_description.json` myself: CC0, the same MD5, equal to the current object's ETag. No credentials appear in any script. The scripts' Python makes no network calls, and build.sh uses only local files.
- **Novelty:** `novelty.py --url …/ds003483/ --terms ds003483 magnetoencephalography neuromag vectorview MEG magnetometer` matched only same-host OpenNeuro recipes and ds004212 (32-bit CTF MEG). There is no MEG in the 16-bit family list locally or downstream, so the label is `new_source`.
- **Volume (accepted):** 900 MB is well above the ~100 MB downstream guidance but under the 1 GB cap. The upstream population is about 9× larger. A time-major layout forces whole-file downloads, so keeping all 102 magnetometers per downloaded run is the efficient choice.
