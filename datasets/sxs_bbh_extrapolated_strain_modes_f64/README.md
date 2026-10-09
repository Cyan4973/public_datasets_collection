# SXS:BBH Extrapolated Asymptotic Strain Modes rh/M (N2, CoM, l<=4) Float64

Native IEEE-754 float64 **gravitational-wave strain modes** `r·h_lm/M` from
SpEC numerical-relativity simulations of binary-black-hole mergers in the SXS
Collaboration catalog. Each sample is one complex spin-weight -2
spherical-harmonic mode of one simulation, real and imaginary parts
interleaved, covering early junk radiation, inspiral, merger and ringdown on
the simulation's non-uniform retarded-time grid.

## Source

- Zenodo community `sxs` (<https://zenodo.org/communities/sxs>), one record
  per simulation, e.g. <https://zenodo.org/records/3301877> (SXS:BBH:0305).
  The 2019 deposits are used. Newer catalog versions (CaltechDATA, v3 RPDMB
  compressed waveforms) are not.
- File: `Lev{N}/rhOverM_Asymptotic_GeometricUnits_CoM.h5` at the highest Lev
  that also has a `metadata.json`. The file is HDF5 with superblock v0
  (written by scri.SpEC/h5py), and its root has four symbol-table groups:
  `Extrapolated_N2.dir`, `Extrapolated_N3.dir`, `Extrapolated_N4.dir`,
  `OutermostExtraction.dir`. Each group holds 77 datasets `Y_l{2..8}_m{-l..l}.dat`
  of float64 `[N, 3]` (t/M, Re, Im), chunked `(C, 1)` (one column per chunk; C≈1,750 rows in
  the probed files) with the shuffle(8) + deflate pipeline and a v1 chunk B-tree.
- Only `Extrapolated_N2.dir` and only l ≤ 4 (21 modes) are read. N3/N4 and
  Outermost are near-duplicate extrapolations of the same waveform. The
  non-CoM file is never touched.

## Rights

Every pinned record's Zenodo metadata declares `"license": {"id": "cc-by-4.0"}`.
`download.sh` re-fetches all 51 record JSONs and stops on any license, title,
file-size or MD5 change. Cite the SXS catalog (Boyle et al. 2019,
arXiv:1904.04831) and the per-simulation record DOIs.

## Selection

`discover.sh` lists the community with `q="SXS:BBH"` (2,165 records; 2,019 are
cc-by-4.0 2019 deposits with a CoM rhOverM file). `scripts/select_sims.py`
sorts the eligible records by SXS:BBH number and keeps every 40th, starting
with the first. That gives **51 simulations**, SXS:BBH:0001 to SXS:BBH:2146,
spread across the catalog's mass ratios, spins, precessing and eccentric runs.
They comprise 39 Lev3, 6 Lev4 and 6 Lev5 files, totalling 4.75 GB as whole
files. `sims.tsv` pins record id, file keys, sizes and Zenodo MD5s.

## Acquisition (byte ranges)

Downloading whole files would keep about 6% of the bytes. Instead,
`download.sh` runs a planner (`scripts/sxs_modes.py plan`) in rounds. The
planner walks each file's HDF5 metadata through a local cache of 64 KiB
aligned blocks and lists the block runs still missing. Those are the
superblock, the root and N2 symbol tables (B-tree, local heap, SNODs), the 21
dataset headers and chunk B-trees, and finally their chunks. Some chunks sit
near EOF, where the CoM rewrite relocated them. `scripts/fetch_range.sh`
accepts a run only if the response is 206 with the exact `Content-Range` and
length.

A dry run on SXS:BBH:1180 converged in 9 rounds, 40 requests and 6.5 MB, from
a 77.6 MB file. The realized download (2026-10-08) converged in 9 planner
rounds for all 51 files. It came to 5,939 blocks plus the 77.6 MB control
file, 466 MB in total under `downloads/`, and took 495 s.

Integrity:

- Every chunk is zlib (Adler-32) checked and must inflate to the exact chunk size.
- `metadata.json` is MD5-checked.
- One complete control file (SXS:BBH:1180) is MD5-checked. `verify.sh` then
  byte-compares every range block of that simulation against it.

## Output

| series | role | sample | count |
|---|---|---|---|
| `sxs_bbh_rhoverm_n2_mode_reim_f64` | primary | one (simulation, l, m): `[N, 2]` float64 LE, Re/Im interleaved | 1,071 (51 × 21), 286,700,400 B, 35,837,550 values |
| `sxs_bbh_rhoverm_n2_retarded_time_f64` | auxiliary | one per simulation: `[N]` float64 t/M | 51, 6,826,200 B |

N ranges from 13,828 to 34,311 rows per simulation. The median primary sample
has 31,850 values.

Across simulations, the median peak |value| per (l, |m|) runs from 3.3e-1
for (2,2) down to 4.5e-3 for (4,0) and (4,2). m=0 modes are not
near-constant: their median peak is 4.6e-2 for l=2 and 4.5e-3 for l=4.

SXS:BBH:0001 (equal mass, non-spinning) is an exception. By symmetry, its 10
odd-m modes are only numerical noise, with peaks of 2e-7 to 9e-7. They are
kept as source data: 10 of 1,071 samples.

The primary payload is native float64. Values span about 1e-9 to 0.4 in
magnitude. h22 peaks around 0.1–0.4 depending on mass ratio. m=0 modes contain
junk-radiation transients and the slowly growing memory, and they are kept.
For non-precessing systems, modes ±m are related by
`h_{l,-m} = (-1)^l conj(h_{l,m})`. They are still distinct source datasets,
and precessing runs break the symmetry.

## Checks

The build checks:

- float64 IEEE datatype and `[N, 3]` shape with N ≥ 1000, the same N for all
  21 modes
- time columns bit-identical across modes and strictly increasing
- all values finite, no constant mode
- the N2 group `space_translation` / `boost_velocity` attributes equal
  `metadata.json` `com_parameters`
- the |h22| peak lies within −150…+250 M of `metadata.json`
  `common_horizon_time`, with amplitude between 0.02 and 0.6

`verify.sh` re-decodes every dataset through a separate row-wise extraction
path, then:

- byte-compares every sample and checks every index row (sizes, sha256,
  min/max)
- rejects stray files
- compares the realized counts and bytes with the manifest
- runs the control-file comparison

## Files

- `sims.tsv` lists the 51 pinned simulations.
- `discover.sh` re-derives `sims.tsv` from the live listing and diffs it.
- `scripts/sxs_h5.py` is a pure-stdlib HDF5 reader, scoped to this layout.
- `scripts/blockstore.py` is the sparse 64 KiB block cache.
- `scripts/sxs_modes.py` holds the planner, build and verify.
- `scripts/fetch_range.sh` fetches one range with curl.
- `scripts/selftest_sxs_h5.py` builds a synthetic HDF5 file. It covers
  multi-level group and chunk B-trees, edge chunks, shuffle+deflate and
  attributes, runs the offline planner→fetch→decode loop and checks that
  corruption is rejected.
