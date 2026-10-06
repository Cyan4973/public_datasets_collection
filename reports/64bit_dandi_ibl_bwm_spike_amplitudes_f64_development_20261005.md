# IBL Brain-Wide Map spike-amplitude float64 development

## Outcome

Accepted `dandi_ibl_bwm_spike_amplitudes_f64` from the published, immutable
DANDI:000409 "IBL - Brain Wide Map" version 0.260309.1324.

This is the first 64-bit neuroscience family in the collection. It differs from
`zenodo_npx_opto_templates_f32`, which holds Kilosort template waveform tensors
(a different quantity, at 32-bit). It also differs from the accepted
DANDI:000020 patch-seq and DANDI:001076 calcium families, which are different
dandisets, modalities and widths. Here one sample is the complete per-spike
amplitude vector of one spike-sorted Neuropixels unit.

## Source and rights

- Source: DANDI:000409 published version 0.260309.1324
  (DOI 10.48324/dandi.000409/0.260309.1324), 459 processed NWB assets from
  139 subjects in 12 labs.
- Pinned assets (whole-file `dandi:sha2-256` identity pins; only byte ranges
  are fetched):
  - zadorlab `sub-CSH-ZAD-001` session 3e7ae7c0, asset f24e825f, blob
    ca4dfea1…, 655,836,490 bytes, sha256 `fe3e00ee…3a0e`
  - danlab `sub-DY-008` session 0f25376f, asset 2a3bbcf9, blob 5dfc5fa1…,
    694,652,180 bytes, sha256 `8eb203fc…245e`
- License: CC BY 4.0. The version metadata declares `license:
  ["spdx:CC-BY-4.0"]` and access `dandi:OpenAccess`, and both asset records
  report OpenAccess. download.sh re-checks identifier, version, name, license,
  access and each asset's path, size, etag, sha2-256, contentUrl, encoding,
  participant and species on every run.
- Access: anonymous S3 byte ranges. Every 206 response must carry
  `Content-Range a-b/<pinned size>` and the pinned DANDI etag.

## Shape and conversion

- Natural record: one row of the NWB Units table, i.e. the slice of
  `/units/spike_amplitudes_uV` (H5T_IEEE_F64LE, chunks of 1,250,000, deflate
  level 4) between consecutive `/units/spike_amplitudes_uV_index` (uint32)
  entries. Values are written unchanged as little-endian float64 microvolts in
  stored order.
- Selection: labs are ordered by their first processed asset in path order,
  with the lab read from `/general/lab`. Each lab's first asset is kept while
  the cumulative stored spike count stays ≤ 62.5M (500 MB), with at most 3
  sessions. Result: zadorlab and danlab; churchlandlab and the 9 later labs
  overflow the budget. discover.sh reproduces `selection.tsv`.
- Units with fewer than 1,000 spikes are excluded (38 zadorlab units with
  12,246 spikes; 174 danlab units with 65,243 spikes). Units are kept
  whatever their quality label.
- Decode: a strict stdlib HDF5 subset reader (superblock v0, v1 object
  headers, symbol-table groups, v1 chunk B-trees) walks 35 cached 64 KiB
  metadata blocks. It then fetches only the 47 amplitude chunks and 2 index
  chunks: 84 ranges, 428,865,052 bytes, with per-range SHA-256 recorded.
  Enforced: chunk count = ceil(N/1.25M), each chunk inflates to exactly
  10,000,000 bytes, valid decoded size = 8N, monotone index with last = N,
  kept-unit and kept-spike pins.
- Width disclosure: the values are float32 Kilosort amplitudes times one
  float64 scale per unit. They are not full 53-bit measurements, but 0 values
  are float32-exact, so float64 is the honest, non-narrowable storage.

## Accepted output

- Sessions: 2 (zadorlab 519 units → 481 kept; danlab 1,014 units → 840 kept)
- Primary samples: 1,321
- Primary values: 57,416,236 (zadorlab 32,017,296; danlab 25,398,940)
- Primary bytes: 459,329,888
- Minimum sample: 1,039 values
- Median sample: 34,405 values
- Maximum sample: 449,676 values
- Value range: 7.18 to 1,241.56 µV; 0 non-finite, 0 non-positive, 0
  float32-exact
- Distinct values per unit: 96.2% to 100% of spikes (median 99.7%)
- Units consistent with float32 × a per-unit scale: 1,321 / 1,321 (LCM 23 to
  24 bits, max relative error 4.4e-16)
- Aggregate sample SHA-256:
  `0ac190be63de4d8ddcad0208bf8ccbbef068a2c0eabf6e0f4323f1131aca1f9f`

## Judge checks

- `gate.py`: PASS, no warnings.
- `verify.sh` run by the judge: exit 0 (self-test with 12 rejection cases,
  1,321/1,321 samples byte-compared, aggregate hash matched).
- Chunk layout: all 26 + 21 amplitude chunk addresses and sizes, plus the
  danlab index chunk, equal the independent neurosift LINDI index for both
  assets.
- Full-file cross-check (danlab): a mistyped judge probe fetched the whole
  pinned blob; it was deleted after this use. Its SHA-256 equals the pinned
  `dandi:sha2-256`. All 40 recorded danlab ranges match it at their offsets.
  A plain-zlib decode via LINDI offsets reproduced all 840 danlab samples byte
  for byte.
- zadorlab: the judge decoded LINDI's inline blosc-lz4 index and summary
  columns with a stdlib LZ4 decoder. Offsets and counts match all 481 samples,
  and the emitted unit rows are exactly the units with ≥ 1,000 spikes.
- Semantics: NWB `spike_count` equals the index differences for 1,533/1,533
  units. Every sample's min and max equal the NWB
  `min/max_spike_amplitude_uV` columns for 1,321/1,321 units. NWB's median
  column differs from the sample median by ≤ 1.7e-7 relative; it is
  apparently computed at lower precision.
- Width: in 10 random whole units, every value is within ~4e-9 float32 ulps
  of a float32 lattice × one per-unit scale (24-bit reference mantissa). A
  perturbed control gives a 3,601-bit LCM. The low 28 mantissa bits are never
  all zero. Precedent: `zenodo_marine_dom_profile_mzml_f64` was rejected
  because its source was stored as float32; this source stores float64.
- Bytes: positive µV amplitudes with a detection-threshold lower edge, low
  lag-1 autocorrelation, no scaled-copy or prefix duplicates across samples.
- Rights: version metadata and the live `/info/` endpoint both show
  CC-BY-4.0 and OpenAccess; asset records are OpenAccess mouse sessions. No
  credentials in any script.
- Novelty: `novelty.py` found no 000409, IBL or spike_amplitudes hits outside
  this staging recipe. There is no 64-bit neuroscience family locally,
  downstream or in the ledger.
