# IBL Brain-Wide Map Neuropixels Unit Spike Amplitudes (DANDI:000409, float64)

Per-spike amplitudes of spike-sorted Neuropixels units from the International
Brain Laboratory (IBL) Brain-Wide Map. The source is the published DANDI
dandiset [000409 "IBL - Brain Wide Map", version 0.260309.1324](https://dandiarchive.org/dandiset/000409/0.260309.1324)
(DOI 10.48324/dandi.000409/0.260309.1324, CC BY 4.0).

## What is collected

- One primary series, `ibl_unit_spike_amplitudes_uv_f64`. One sample is the
  complete amplitude vector of one spike-sorted unit: the slice of the NWB
  ragged column `/units/spike_amplitudes_uV` between consecutive entries of
  `/units/spike_amplitudes_uV_index`. The values are little-endian float64 in
  microvolts, bit-identical to the stored values, in stored order (aligned
  element by element with that unit's `spike_times`, which this recipe does not
  collect). The NWB description reads "Peak amplitude of each spike for each
  unit in microvolts."
- Two complete sessions, one from each of two labs. Both use the same pipeline:
  IBL's iblsorter (Python Kilosort 2.5) on Neuropixels 1.0 probes, mice doing
  the IBL decision task, exported to NWB 2.9.0.

| lab | institution | subject / session | units | kept (>= 1,000 spikes) | dropped | kept spikes |
|---|---|---|---|---|---|---|
| zadorlab | Cold Spring Harbor Laboratory | CSH_ZAD_001 / 3e7ae7c0 | 519 | 481 | 38 (12,246 spikes) | 32,017,296 |
| danlab | UC Berkeley | DY_008 / 0f25376f | 1,014 | 840 | 174 (65,243 spikes) | 25,398,940 |

Realized output: 1,321 samples, 57,416,236 values, 459,329,888 bytes. Samples
run from 1,039 to 449,676 values (median 34,405); the largest is 3.6 MB. The
value range is 7.18 to 1,241.56 µV (zadorlab 7.18 to 569.07; danlab 9.04 to
1,241.56). The realized build found 0 non-finite values, 0 non-positive values
and 0 float32-exact values. Distinct values per unit are 96.2% to 100% of the
unit's spike count (median 99.7%).
Kept units and spikes are pinned in `sessions.tsv`, and the aggregate SHA-256
over the sample hashes in index order is
`0ac190be63de4d8ddcad0208bf8ccbbef068a2c0eabf6e0f4323f1131aca1f9f`. Build
and verify both enforce these.

Units are kept whatever their Kilosort or IBL quality label: every row is a
genuine spike-sorted cluster with the same quantity and unit. Units with fewer
than 1,000 spikes are dropped so that each sample clears the per-sample floor.
Excluded as different quantities: `spike_times`,
`spike_distances_from_probe_tip_um` (which is float32-exact), `waveform_mean`,
and all per-unit summary columns (firing rate, quality metrics,
median/min/max amplitude, and so on).

## Width disclosure (read this)

These are **not** full-precision float64 measurements. Within each unit, every
amplitude equals a **float32 per-spike Kilosort amplitude times one per-unit
float64 scale**. The scale is consistent with the unit template's amplitude
times the probe gain, expressed in µV. The IBL/phylib amplitude definition is
the Kilosort template-scaling amplitude times the template's peak-to-trough
amplitude times the gain. We verified the structure empirically, not the exact
factorisation.

Evidence comes from the ratio/LCM test (`scripts/scale_test.py`). If
v_i = fl(x_i * s) with float32 x_i, then v_i / v_ref equals x_i / x_ref up to a
few ulps. With the power of two removed, that is a ratio of 24-bit integer
mantissas: its best rational approximation with denominator < 2^24 matches to
about 2e-16, and the LCM of the denominators stays within 24 bits. Probe
results on chunk 0 of the zadorlab session (the first 1,250,000 values):

- 0 of 1,250,000 values are float32-exact. Nor is any of the first 20,000
  values float32 × a global constant from {1e-6, 1e-3, 0.1, 1, 10, 1e6,
  2.34375, 0.195, 1/0.195}.
- All 23 units lying wholly in chunk 0 (1,151,321 values) have LCM ≤ 24 bits
  over up to 300 random ratios per unit. For the first 21 units the maximum
  relative error is 2.2e-16 to 4.0e-16. A generic float64 control gives an
  LCM of 5,055 bits and a median error of 2.1e-15. A synthetic
  float32 × constant control gives 24 bits and 0 error.
- After recovering an approximate per-unit scale, every value lies within
  about 1 ulp of float32 × scale. Only about 51% are reproduced exactly by a
  single multiplication, which suggests more than one rounding step upstream
  (for example, template amplitude × gain, then × 1e6).

build and verify run the test (64 evenly spaced ratios) on every kept unit.
They record `f32_ratio_lcm_bits`, `f32_ratio_max_rel_err` and
`float32_exact_values` in the index, and the per-session totals in
`ingest_stats.json`. Realized result: **all 1,321 kept units (481/481
zadorlab, 840/840 danlab) are consistent with float32 × a per-unit
constant**. Their LCMs are 23 or 24 bits and their maximum relative error is
4.4e-16. **0 of the 57,416,236 values are float32-exact.** The width is still honest storage: the column cannot be
narrowed to float32 unless the per-unit scale is also stored. Expect a model to
learn this structure (24 significant bits times a constant per sample) rather
than 53-bit entropy.

## Session selection (deterministic)

Rule (`scripts/discover_sessions.py`, reproduced by `discover.sh`):

1. Take the published version's 459 processed assets
   (`*_desc-processed_behavior+ecephys.nwb`) in path order.
2. Read `/general/lab` from the first asset of every subject (139 subjects,
   12 labs). The subject-name prefix is not a reliable lab key: `SWC-*`
   subjects belong to both `mrsicflogellab` and `hoferlab`, and `MFD-*` and
   `UCLA-*` are both `churchlandlab_ucla`.
3. Walk labs in the order of their first processed asset. For each lab take
   that first asset, and keep it only if the cumulative stored spike count of
   kept sessions stays at or below 62,500,000 (500 MB of float64). Stop at
   three sessions.

Result (`selection.tsv`): zadorlab (32,029,542 spikes) is kept. churchlandlab
(43,284,928) is skipped because the total would reach 75.3M. danlab
(25,464,183) is kept, for a total of 57,493,725. Every later lab's first
session would exceed the budget (smallest: hausserlab at 16,281,689, giving
73.8M), so the result is two sessions from two labs. The 500 MB budget follows
the screener's guidance of about 330 to 500 MB primary. Downstream sub-samples
roughly 100 MB per family.

## Access and decode

Each processed NWB file is 0.5 to 1.3 GB. The recipe fetches only what it
needs, using anonymous HTTP byte ranges of the content-addressed S3 blob listed
in the asset's own `contentUrl`. No credentials are used. Each 206 response
must carry `Content-Range: bytes a-b/<pinned size>` and the pinned DANDI etag
(the S3 ETag of the whole object), so every range provably comes from the
pinned blob.

1. `download.sh` fetches the version metadata and checks identifier, version,
   license `["spdx:CC-BY-4.0"]` and `dandi:OpenAccess`. It then fetches both
   asset records and checks path, size, etag, sha2-256, blob URL, NWB encoding,
   access and participant id against `sessions.tsv`.
2. HDF5 metadata. `scripts/ibl_amplitudes.py meta-plan` walks the superblock v0
   → root symbol table → `/general` (lab, institution, session_id,
   subject_id) and `/identifier` → `/units` → both dataset headers → their v1
   chunk B-trees. It reads over a sparse cache of 64 KiB blocks and exits 3
   listing each missing block; curl fetches those blocks and the walk repeats.
   This takes about 18 rounds and about 2.3 MB in total, and was verified
   against the live files during authoring.
3. Data. curl fetches the exact compressed byte range of each chunk: 26 + 21
   amplitude chunks (426,565,869 bytes) plus the two index chunks
   (5,423 bytes).
4. `inventory` re-validates everything locally and inflates every chunk. Each
   chunk must inflate to exactly 10,000,000 bytes, the chunk count must equal
   ceil(N / 1,250,000), the valid decoded size must equal 8N, the index must
   be monotone with last entry = N, and kept units and spikes must match the
   pins. It writes the SHA-256 of every fetched range to `range_sha256.tsv`.
   A corrupt chunk is deleted so that a re-run re-fetches it.

Realized download: 428,929,150 bytes in 120 s. That is 84 recorded ranges
totalling 428,865,052 bytes: 426,571,292 bytes of chunk ranges plus 35
metadata blocks of 64 KiB, as listed in `range_sha256.tsv`. The rest is small
JSON and planning files. Re-runs skip complete ranges.

`scripts/nwb_hdf5.py` is the strict standard-library HDF5 subset reader from
the accepted DANDI:001076 recipe, extended with the block cache and 1-D
chunked helpers. It accepts only superblock v0, v1 object headers,
symbol-table groups, `H5T_IEEE_F64LE` amplitudes, a `H5T_STD_U32LE` index, a
deflate-only filter, filter mask 0, and an exact chunk grid. The LINDI JSON
index on neurosift was used only as an authoring cross-check and is never read
by the recipe.

## Validation

- `scripts/selftest.py` writes a synthetic NWB-like HDF5 file byte by byte:
  vlen strings in a global heap, a two-level root B-tree, a continuation
  block, a multi-chunk f64 column with an edge chunk, and a u32 index. It
  requires bit-exact unit slices, a `MissingBlock` report for an absent block,
  correct separation by the scale test, and rejection of these cases: missing
  chunk, duplicate chunk, filter mask, truncated deflate, float32 dtype,
  shuffle filter, non-monotone index, wrong last index, wrong chunk length,
  wrong lab, bad EOF and bad signature. download.sh, build.sh and verify.sh
  all run it first.
- `build.sh` re-parses the cached metadata and checks every block and range
  against `range_sha256.tsv`. It streams unit slices chunk by chunk and
  rejects non-finite values, constant units and duplicate samples. It writes
  the samples, `samples.jsonl` (with lab, subject, session, asset, unit row,
  ragged offset, min, max, distinct count, non-positive count, float32-exact
  count, the scale-test result and sha256), and `ingest_stats.json`.
- `verify.sh` (`scripts/verify_amplitudes.py`) re-hashes every range and
  rebuilds each session's whole vector by placing inflated chunks at their
  B-tree offsets, a different strategy from build's streaming. It
  byte-compares every sample, recomputes every index field and the aggregate
  hash, rejects stray files, and checks the manifest `sample_count` and
  `total_size_bytes`.

## Running

```bash
bash staging/dandi_ibl_bwm_spike_amplitudes_f64/download.sh   # ~429 MB of ranges
bash staging/dandi_ibl_bwm_spike_amplitudes_f64/build.sh
bash staging/dandi_ibl_bwm_spike_amplitudes_f64/verify.sh
bash staging/dandi_ibl_bwm_spike_amplitudes_f64/discover.sh   # optional provenance, ~19 MB of probes
```

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/dandi_ibl_bwm_spike_amplitudes_f64/`.

## Caveats

- Width: see the disclosure above. This is float32 × per-unit-scale material
  stored as float64, not pipeline-native full-precision float64.
- The amplitudes are template-fit outputs of spike sorting, not raw ADC
  samples. Neighbouring families: `zenodo_npx_opto_templates_f32` (Kilosort
  template waveforms: a different quantity and width) and the accepted
  DANDI:001076 calcium-fluorescence family (a different dandiset, modality and
  width). No local or downstream 64-bit neuroscience family exists.
- Two sessions from two labs. This is a bounded subset of a 459-session
  dandiset, chosen by the rule above rather than by inspecting values.
- Units from both probes of a session (where two were inserted) are emitted
  alike. The probe of each unit is not recorded, because `probe_name` is a
  variable-length string column that the recipe does not read.
