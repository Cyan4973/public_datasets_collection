# OpenNeuro ds007738 whole-head CW-fNIRS raw intensity float64 development

## Outcome

Accepted `openneuro_ds007738_wholehead_cw_fnirs_intensity_f64`. It holds all 24 resting-state runs of OpenNeuro ds007738 "Whole-Head Cocktail Party fNIRS" (snapshot 1.0.0; Boston University, Boas / Yücel / Sen labs). Each sample is one complete raw continuous-wave near-infrared intensity matrix, kept bit for bit as native little-endian float64.

This is the first diffuse-optical neuroimaging material in the corpus at any width. The other OpenNeuro families are fMRI BOLD, T1w MRI, cortical thickness, DTI, MEG (two) and EEG. The measured nearest family is `wohns_unified_genealogy_node_time_f64`, at distance 0.0966 with 6.25% compression loss (verdict OK).

## Source and rights

- Source: `s3.amazonaws.com/openneuro.org/ds007738/` (anonymous S3). It holds 223 SNIRF runs (38.8 GB) over the tasks overt, covert, visualorient, longvisualorient/videoattend and resting.
- Collected: the 24 `*_task-resting_run-01_nirs.snirf` objects, one per subject: sub-01..05, 10, 11, 13, 14, 15, 18, 20, 22, 23, 24, 25, 28, 29, 32, 33, 35, 41, 44, 46. Together they total 2,392,745,456 file bytes.
- Pins: each file's size and S3 ETag are pinned in `runs.tsv`. Every 206 response must carry the pinned ETag and `Content-Range */<size>`.
- License: CC0. The snapshot's `dataset_description.json` declares `"License": "CC0"` and `"DatasetDOI": "doi:10.18112/openneuro.ds007738.v1.0.0"`. `CHANGES` shows `1.0.0 2026-05-01`, the only snapshot. download.sh re-checks the license, DOI, dataset name and CHANGES on every run.
- Privacy: the README states the dataset holds only fNIRS and eye-tracking time series, shared under IRB consent. Only the optical intensity matrix is emitted. Aux (eye tracking), stim, probe geometry and metaDataTags are never fetched as payload.

## Shape and conversion

- Natural record: one sample is the complete `/nirs/data1/dataTimeSeries` of one resting run, which is 5+ minutes of central fixation with no task.
- Shape: T x 1134 source-detector-wavelength channels (56 sources, 144 detectors, 760/850 nm), sampled at about 8.99 Hz. Order is the stored row-major order, time-major.
- Decode path:
  - The HDF5 metadata (superblock v0, symbol-table groups) is walked with the IBL standard-library reader over cached 1 MiB range blocks. The dataset address and size come from the object header and are not hard-coded.
  - The exact contiguous byte range is fetched with resumable range requests and copied unchanged.
- Required in every run:
  - the dataset is contiguous, unfiltered H5T_IEEE_F64LE;
  - the shape is (T ≥ 1000, 1134) and the size is T·1134·8;
  - every `measurementList*/dataType` is 1 (raw CW amplitude);
  - the wavelengths are (760, 850);
  - the channel table (source, detector, wavelength, dataType, dataTypeIndex) hashes to the pinned `d8099a28…`, so channel k means the same optode pair and wavelength in every sample.
- Excluded: the task runs, the time vector, aux, stim, probe geometry, metaDataTags, and other OpenNeuro fNIRS datasets (whose devices and export precision differ).
- Missing values are kept as stored:
  - the 1e-6 stand-in written by the export: 3.02% of values overall, 0.18–15.4% per run;
  - exact zeros: 0.037%;
  - the quiet NaN `0xFFF8000000000000` in frame 0 only of the 13 runs sub-20..sub-46 (908–1,063 values per run, 0.016% overall).
- Fatal in download, build and verify: any other NaN pattern, ±Inf, more than 0.5% NaN, a constant matrix, fewer than 20% distinct values, or more than a quarter of channels constant.

## Accepted output

- Primary series: `cw_fnirs_raw_intensity_f64` (float64, little-endian)
- Samples: 24
- Values: 80,828,118
- Bytes: 646,624,944
- Frames per sample: 2,832 to 3,207. Sample size: 25,691,904 to 29,093,904 bytes. Median: 3,344,733 values.
- Value range: 0 to 0.93901 (arbitrary instrument units). No negative values. 202,202 positive values lie below 1e-6.
- Distinct values per run: 30.3% (sub-04) to 70.2% (sub-28)
- Constant channels per run: 0 to 13 (only in sub-01..sub-18)
- Downloaded: 887,154,957 bytes of ranges and metadata
- Aggregate sample SHA-256: `a508327917aaa7ed0e751ce785b000461e759c60acc4274aa9da73df5315e68a`

## Judge checks

- **Mechanics and reproducibility:** `gate.py` passes with no warnings. I re-ran `verify.sh` and it exited 0 and reproduced the aggregate SHA-256 above. `build.sh` reads only cached local blocks and ranges; there is no network code in the build or verify path. No credentials appear in any script. The driver's download log shows `metadata_ok` (1,023 keys, 223 SNIRF runs, 24 resting), `meta_plan_ok` and `inventory_ok`.
- **Bytes:** inspected with stdlib `array`/`struct` on sub-01, sub-04, sub-28 and sub-46, and on all 24 runs for the scale test.
  - Channel medians run from 1e-6 (dark long-separation channels) to 0.91, with a saturation edge near 0.90–0.94.
  - The median frame-to-frame relative change is 0.2–0.6%: smooth physiological traces.
  - Frame-level hashes over 71,253 frames found no duplicate frames within or across samples.
- **Width:** a stronger and more exact finding than the recipe's per-channel LCM disclosure.
  - Every positive value except the floor, in all 24 runs and all channels, is an integer k divided by exactly 7,765,779, to within 3.6e-8 counts. k is at most 7,292,171, i.e. 23-bit counts with one global scale.
  - About 64% of values equal `k/7765779` bit for bit. About 20% differ by one or more ulps (relative error up to about 6e-13 near 2e-6), which points to an upstream arithmetic step such as a difference of scaled counts.
  - Only exact zeros are float32-exact.
  - So the content is about 23-bit counts, but the stored float64 bits cannot be narrowed without loss or side information. Float64 is the publisher's native storage, as in the accepted `dandi_ibl_bwm_spike_amplitudes_f64` precedent.
  - The 1e-6 value is not a count multiple (7.77 counts), so it is an inserted stand-in. It is source-written and at most 15.4% of a run, not a dominating fill.
  - The recipe's README and manifest describe this more weakly: "per-channel scale; 57–99% of channels pass". This report is the precise record.
- **Rights:** I read the downloaded `dataset_description.json` (CC0, DOI), `CHANGES` (single snapshot 1.0.0), README.txt (privacy statement) and `participants.tsv` (IDs only).
- **Novelty:** `novelty.py` with the dataset and S3 URLs and the terms fNIRS, SNIRF, NIRS, near-infrared, optode, diffuse optical and hemodynamic found only same-host matches to the 7 non-optical OpenNeuro recipes. The term matches were astronomy and Landsat only, with no registry or downstream hits. `--type`, `--instrument` and `--archive` all return 0. No downstream 64-bit family is neuro or optical.
- **Homogeneity:** one device, one pinned channel table, one quantity, one task. The same 1/7,765,779 count step holds in every run, which confirms a single acquisition and export chain across both the NaN and no-NaN export variants.
- **Volume:** the entire resting population of the snapshot (24 runs) is taken. That is about 6x the roughly 100 MB downstream need and keeps 73% of the bytes fetched. The task runs are left out on purpose as a different scope.
