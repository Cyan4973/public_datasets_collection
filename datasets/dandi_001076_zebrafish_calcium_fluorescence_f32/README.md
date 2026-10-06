# DANDI:001076 Larval-Zebrafish Two-Photon Suite2p ROI Fluorescence (float32)

Raw Suite2p ROI fluorescence traces (`F`) from the DANDI dandiset
[001076 "OMR Robot CaImaging"](https://dandiarchive.org/dandiset/001076/draft)
(Loring 2024; CC BY 4.0). The dandiset holds the two-photon calcium-imaging data
for the manuscript *Embodied Neural Visuomotor Circuits in Neuromechanical
Simulations and a Zebrafish Robot*: 5 dpf larval zebrafish expressing nuclear
H2B-GCaMP6s, imaged during optomotor-response experiments.

## What is collected

- One primary series, `suite2p_roi_fluorescence_f32`, with one sample per NWB
  file (48 files = 12 acquisition sessions x 4 imaging objects).
- Each sample is the complete
  `/processing/ophys/Fluorescence/RoiResponseSeries/data` matrix: frames x ROIs,
  row-major, little-endian IEEE float32, bit-identical to the stored values.
  NWB declares `unit = "n.a."`, `conversion = 1.0`, `offset = 0.0`, and the
  series description is "Array of raw fluorescence traces."
- Shapes run from 1,380 to 1,420 frames (about 0.85 to 0.94 Hz, roughly 26 min)
  and 535 to 1,616 ROIs. Totals: 62,819,025 values, 251,276,100 bytes, median
  1,227,534 values per sample.
- Excluded as different quantities: `Neuropil` (Fneu), `Deconvolved` (spike
  inference), PlaneSegmentation `image_mask`, `ROICentroids`, the
  `Accepted`/`Rejected` flags, the float64 mean and correlation images, and the
  trial table. Every ROI column is kept, including ROIs that Suite2p's
  classifier rejected, because the full stored matrix is the natural record.

Each NWB file holds exactly one `ImagingPlane` and one `PlaneSegmentation`, so
a sample is one Suite2p plane extraction. Within a session the four objects
differ in ROI count, frame count (by up to 4 frames), imaging rate and
crop size. The files carry no plane index, location (`unknown`) or depth, so
the index records the DANDI `obj-*` token and session id as bookkeeping rather
than claiming a plane number. build/verify reject duplicate decoded samples and
duplicate NWB identifiers. A post-build check found the objects within a session
are distinct fields of view. Same-size stored mean images correlate at
r = 0.27 to 0.94, where a reprocessed copy of one movie would give r = 1. ROI
and frame counts also differ. Their population-mean F traces correlate at
r = 0.62 to 0.97, as expected for neighbouring planes of one larva under the
same stimulus.

Realized output: 48 samples, 62,819,025 values, 251,276,100 bytes, range
-125.35 to 1202.02, 0 non-finite values, 266 negative values, 2 exact zeros,
0 constant ROI columns, and 736,226 to 2,054,344 distinct values per sample.
Aggregate SHA-256 over the samples in asset-path order:
`7b3e1782536df105533b7c7f25f53a0e98fc2e28f11dd2bd22f83d3f7e18e950` (enforced by
build and verify).

## Source pinning

DANDI:001076 has **no published version** (API `most_recent_published_version:
null`; draft last modified 2024-06-27, status Valid). The recipe therefore pins
the draft asset set in `assets.tsv`: asset path, asset id, content-addressed S3
blob URL, `contentSize`, `dandi:sha2-256`, plus NWB identifier, session start,
frames, ROIs and chunk count, all taken from header-only range probes.
`download.sh` re-fetches the draft `dandiset.yaml` (license `spdx:CC-BY-4.0`,
`dandi:OpenAccess`) and `assets.yaml`, and fails unless the live asset set
equals the pin exactly. Note that `dandiset.yaml`'s `assetsSummary` (42 files)
is stale; `assets.yaml` and the API both report 48 assets and 660,278,264 bytes.

## Decode

`scripts/nwb_hdf5.py` is a strict standard-library HDF5 subset reader. It
supports superblock v0 with 8-byte offsets, v1 object headers with
continuations, symbol-table groups, simple dataspaces, numeric and string
attributes (including variable-length strings from the global heap), and
v1 raw-data chunk B-trees. For each file `scripts/build_fluorescence.py`:

1. checks size and `dandi:sha2-256`, NWB root attributes (`NWBFile`, 2.6.0),
   identifier, session start, species and subject line;
2. checks the RoiResponseSeries type and description and the data attributes
   (`unit`, `conversion`, `offset`, `resolution`), the pinned shape, `rois`
   length and PlaneSegmentation ROI count;
3. requires `H5T_IEEE_F32LE`, a deflate-only filter pipeline, filter mask 0,
   and an exact chunk grid with no missing or duplicate chunks. 46 files store
   one chunk equal to the full shape; two files
   (`ses-20230123T214030_obj-10jcyv7`, `_obj-1xqxs27`) store two ROI-axis
   chunks of width 1,581, and only their edge padding is discarded;
4. inflates each chunk to exactly its full size and assembles the logical
   matrix, whose length must equal frames x ROIs x 4;
5. requires all values to be finite (NaN/Inf is fatal) and the matrix to be
   non-constant, and records min, max, mean, distinct-value count, zero and
   negative counts, and constant ROI columns in the index.

`scripts/selftest_nwb_hdf5.py` writes synthetic HDF5 files byte by byte and
checks exact reconstruction for single-chunk and edge-padded grids. It also
checks rejection of missing, duplicate and filter-skipped chunks, truncated
deflate, big-endian float, an extra shuffle filter, and EOF/signature
corruption. `build.sh` and `verify.sh` run it first.

`verify.sh` re-hashes every source, decodes it again, byte-compares each sample,
rebuilds every index row and the aggregate statistics, rejects stray files, and
checks the manifest `sample_count` and `total_size_bytes` against the realized
output.

## Running

```bash
bash staging/dandi_001076_zebrafish_calcium_fluorescence_f32/download.sh   # ~660 MB
bash staging/dandi_001076_zebrafish_calcium_fluorescence_f32/build.sh
bash staging/dandi_001076_zebrafish_calcium_fluorescence_f32/verify.sh
```

All scripts honor `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/dandi_001076_zebrafish_calcium_fluorescence_f32/`.

## Caveats

- Neuroscience-adjacent: this sits beside the accepted OpenNeuro families and
  the Kilosort template family, but it is the first optical-physiology
  (calcium-imaging ROI trace) family, locally or downstream.
- `F` is a Suite2p derived output (mean ROI pixel intensity per frame), not
  raw movies; this dandiset does not publish the raw movies.
- Single lab, single subject label (`sub-nan`) and two recording days. The
  12 sessions x 4 objects are homogeneous in microscope, indicator, pipeline
  and unit.
