# DANDI:001076 zebrafish Suite2p ROI fluorescence float32 development

## Outcome

Accepted `dandi_001076_zebrafish_calcium_fluorescence_f32`, built from all 48 NWB
ophys assets of DANDI:001076 "OMR Robot CaImaging" (Loring 2024). It is the
first optical-physiology (calcium-imaging ROI trace) family, locally or
downstream. Local 32-bit is already neuro-heavy (OpenNeuro MRI/DTI/cortical
thickness/MEG/EEG, Neuropixels templates, MouseLight neuron trees), but this is
a distinct measurement modality.

## Source and rights

- Source: DANDI Archive dandiset 001076, draft (no published version;
  last modified 2024-06-27; API status Valid, embargo OPEN)
- Assets: 48 NWB 2.6.0 files, 8,642,925 to 22,085,626 B each, 660,278,264 B
  in total. They are content-addressed S3 blobs, each pinned with
  `dandi:sha2-256` in `assets.tsv`.
- License: CC BY 4.0 (`license: - spdx:CC-BY-4.0`, `dandi:OpenAccess` in the
  draft `dandiset.yaml`; the live API shows the same).
- `download.sh` re-checks license and access on every run. It fails unless
  the live draft `assets.yaml` (path, asset id, blob URL, size, sha256) equals
  the 48 pinned rows exactly. The stale `assetsSummary` (42/44 files) is
  documented.

## Shape and conversion

Each natural record is one NWB imaging object, which is one Suite2p plane
extraction. Its sample is the complete
`/processing/ophys/Fluorescence/RoiResponseSeries/data` matrix: frames x ROIs,
row-major, stored `H5T_IEEE_F32LE` bit patterns unchanged. A pure-stdlib HDF5
subset reader decodes it under these checks:

- superblock v0, v1 object headers, symbol-table groups;
- deflate-only filter, filter mask 0, exact chunk grid and exact inflate
  length;
- `unit` n.a., `conversion` 1, `offset` 0;
- pinned shape, NWB identifier and session start; `rois` and
  PlaneSegmentation ROI counts equal the ROI axis.

46 files store one full-shape chunk. Two files in session 214030 store two
ROI-axis chunks of width 1,581, and only their zero edge padding is
discarded.

Excluded as different quantities: Neuropil, Deconvolved, image masks,
centroids, accept/reject flags, mean/correlation images and trials. Every ROI
is kept, including classifier-rejected ROIs. NaN/Inf are fatal; none exist.

## Accepted output

- Primary samples: 48 (12 sessions x 4 objects)
- Primary values: 62,819,025
- Primary bytes: 251,276,100
- Sample size: 752,745 to 2,231,696 values, median 1,227,534
- Shapes: 1,380-1,420 frames (0.85-0.94 Hz) x 535-1,616 ROIs
- Range: -125.35 to 1202.02; 266 negative values, 2 zeros, 0 non-finite,
  0 constant ROI columns
- Distinct values per sample: 736,226 to 2,054,344
- Aggregate decoded SHA-256:
  `7b3e1782536df105533b7c7f25f53a0e98fc2e28f11dd2bd22f83d3f7e18e950`

## Judge checks

- `gate.py` passed with no warnings. I ran `verify.sh` myself and it passed:
  self-test, source re-hash, re-decode and byte-compare of all 48 samples,
  index/stats rebuild, aggregate SHA.
- The download log (22:22) postdates the last edits to `download.sh` and
  `assets.tsv`. It shows the license and asset-set validation passing and
  all 48 files sha256-validated. build and verify contain no network calls
  or credentials.
- **Independent decode.** I scanned the raw file obj-up3yr8 for zlib streams
  without the builder's path walker and found exactly 3 streams of
  1407x535x4 B. The sample is byte-identical to the F stream. The other two
  have Neuropil-like statistics (34..268) and Deconvolved-like statistics
  (520k zeros).
- **2-chunk dechunking (obj-10jcyv7).** The left block equals one stream
  exactly. The right 35 columns equal another stream's valid region, and its
  padding is all zero. The boundary columns have the same temporal
  autocorrelation (0.400 vs 0.402).
- **Orientation.** Lag-1 autocorrelation is 0.43-0.65 along frames and about
  0 across ROIs and under the transposed reading.
- **Not reprocessed copies.** Across all 72 within-session pairs, ROI-centroid
  coincidence (1 px neighbourhood, best shift ±8 px) is 0.095-0.353, about
  random for this ROI density. Shift-aligned mean images correlate at
  r 0.26-0.94. For 60 random ROIs, the best-matching trace in a sibling
  object has r ≤ 0.83 (none above 0.95), against a cross-session baseline
  max of 0.46. The four objects are distinct neighbouring planes with
  shared stimulus drive.
- **Rights.** I read the license in the fetched `dandiset.yaml` and
  re-confirmed it against the live DANDI API. Novelty checked with
  `novelty.py` (URLs plus calcium-imaging/suite2p/ophys/NWB/zebrafish terms):
  no family exists locally, in the registry or downstream.
- **Caveats.** The source is draft-only, but the pin is fail-closed. F is a
  Suite2p derived product; this dandiset publishes no raw movies. There is
  one subject label (`sub-nan`) and two recording days.
