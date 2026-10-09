# Hyburn argon decompression: near-vent pressure slices (float64)

Gas pressure in pascals on the published 500 x 500 near-vent 2-D cross-section
of a 3-D compressible hydrodynamics simulation (Hyburn, built on AMReX). The run
models a Special Technologies Laboratory shock-tube shot: pure argon decompressing
from 1000 psi through a nozzle into an expansion chamber at atmospheric pressure.
The upstream files store pressure as native little-endian float64. This recipe
keeps the IEEE-754 bit patterns exactly as published.

- Source: Zenodo record 4127362, version 1.0.0, DOI 10.5281/zenodo.4127362,
  *Compressible Hydrodynamics Simulation Data for "Standing Shock Prevents
  Propagation of Sparks in Supersonic Explosive Flows"* (von der Linden et al.,
  2020).
- License: CC BY 4.0. The Zenodo API returns `metadata.license.id = "cc-by-4.0"`
  for this record, and `download.sh` re-checks it on every run.

## What is collected

The record holds 785 `numpy.savez` archives. There are 394 `tube_NNNNNN.npz`
files (inside the shock tube) and 391 `near_vent_NNNNNN.npz` files (the
expansion chamber above the nozzle; snapshots 0 to 393, with 46, 100 and 319
absent upstream). Each archive has 33 `.npy` members: 30 fields, plus `mesh`,
`time` and `loadbalance_cost_func`. One near_vent archive is about 23 MB.

This recipe takes exactly one field from one window:

- `pressure.npy` from `near_vent_*` archives, with NPY header
  `{'descr': '<f8', 'fortran_order': False, 'shape': (1, 500, 500)}`.
  One snapshot gives one sample of 250,000 float64 values (2,000,000 bytes),
  stored row-major as the published 500 x 500 slice.
- Excluded: the `tube_*` window (a different region whose interior is mostly
  uniform), the other 32 members, and the particle fields (all zero, because
  the run had no particles).

Selection rule, pinned in `scripts/near_vent_members.tsv`:

1. **Stride 2.** Only even snapshot numbers are kept. Consecutive outputs are
   about 15 µs apart and strongly correlated. Downstream use samples about
   100 MB per family, so every second frame is plenty. Snapshots 46 and 100 are
   absent upstream and are even, so they are simply missing.
2. **Exclude the quiescent pre-jet window.** Before the jet reaches and fills
   the near-vent window, the slice is ambient air: 101325 Pa with about 1e-8 Pa
   of round-off noise, giving only about 400 distinct values over 250,000
   cells. Because the fill is not a single exact value, a dominant-value test
   alone does not catch it (snapshot 0 has a top-value share of only 0.21).
   The rule therefore uses the **ambient fraction**: the share of cells with
   `|p - 101325 Pa| <= 1 Pa`. A snapshot is kept only if its ambient fraction
   is at most 0.5. As a generic guard, its most frequent float64 value must
   also cover at most 0.5 of the cells. `discover.sh` measured both quantities
   on every snapshot up to 80. `build.sh` and `verify.sh` recompute them on
   every kept snapshot and fail if any violates the rule.

## Access path (no full archives)

`discover.sh` is a metadata-only probe, a few MB in total, and has already
been run. For each near_vent archive it range-fetched the last 8 KiB (ZIP
central directory and the `time.npy` member) and the `pressure.npy` local
header. It pinned the member offset, header length, compressed size, CRC32 and
simulation time, together with the archive size and Zenodo MD5, in
`scripts/near_vent_members.tsv`.

`download.sh` performs these steps:

1. Re-validates the record identity, the CC BY 4.0 license, the near_vent file
   count, and every archive size and MD5 against the pinned table.
2. For each selected snapshot, fetches the archive tail by exact byte range.
   It requires `206` with the exact `Content-Range`, re-parses the central
   directory, checks the pinned `pressure.npy` entry, and decodes `time.npy`.
3. Fetches exactly the `pressure.npy` local header plus its DEFLATE data
   (about 1.4 MB per snapshot mid-run). It validates the local header against
   the pinned values, inflates the member, checks its CRC32, size and NPY
   header, and requires all values to be finite and positive. A bad range is
   deleted and refetched up to three times.

`build.sh` inflates each stored member again, checks the CRC32 and NPY header,
applies the selection rule, and writes the 2,000,000-byte float64 payload
verbatim as `samples/<id>/near_vent_pressure_pa_f64/near_vent_NNNNNN_pressure.f64`.
`verify.sh` re-inflates each member on its own and byte-compares it with the
sample. It recomputes finiteness, positivity, distinct-value count (at least
1000), dominant-value fraction, ambient fraction, min/max and SHA-256, rejects
duplicates, and checks that the manifest's `sample_count` and
`total_size_bytes` match the realized output.

## Realized output (build of 2026-10-09)

- 180 samples (even snapshots 30 to 392), each 250,000 float64 values, for
  360,000,000 bytes in total. All 180 SHA-256 hashes are distinct.
- Simulation time runs from 0.427 ms (snapshot 30) to 6.68 ms (snapshot 392).
  Pressure ranges from 1,309.65 Pa to 866,938 Pa.
- The maximum ambient fraction is 0.465 (snapshot 30), and every other kept
  snapshot is below 0.01. The maximum dominant-value fraction is 0.072
  (snapshot 30). The mean uniform-2x2-block fraction is 0.0042.
- Distinct values per sample range from 123,535 (snapshot 30) to 212,862. Many
  mid-run snapshots have exactly 212,862 distinct values; later ones have
  192,646 or 202,321 to 202,322. These plateaus come from a fixed mapping of
  slice cells onto AMR cells for each grid configuration, so the number of
  distinct cells is set by the grid, not by the flow.

## Caveats

- These are the authors' post-processed uniform slices of the AMReX plotfiles,
  not the plotfiles themselves. Where the slice crosses coarser AMR levels,
  neighbouring cells can repeat the same value. In snapshot 202, 2.4% of
  horizontal and 12.4% of vertical cell pairs repeat, and 0.3% of 2x2 blocks
  are fully uniform. This is native to the published product and is kept
  as is. The per-sample `uniform_2x2_block_fraction` is recorded in the index.
- Consecutive kept snapshots (about 30 µs apart) are still temporally
  correlated. All samples come from one simulation run.
- The index carries the simulation time `time_s` from `time.npy` as metadata
  only. It is not an emitted series.
