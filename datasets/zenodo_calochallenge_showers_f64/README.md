# Zenodo CaloChallenge calorimeter showers float64 — staging

This candidate targets native little-endian float64 per-cell energy deposits
from Fast Calorimeter Simulation Challenge 2022 Dataset 2.  Its synthetic
electron showers use a regular cylindrical detector with 45 layers, 9 radial
bins, and 16 angular bins: 6,480 values per independent event.

The exact Zenodo record `10.5281/zenodo.6366271` declares CC BY 4.0.  Its
training file contains 100,000 events but is too large to acquire and emit in
full.  The intended recipe will therefore range-fetch a deterministic bounded
set of complete HDF5 chunks and emit complete natural shower events.  It will
never split an event, concatenate events into artificial samples, or mix the
separate `incident_energies` field into shower bytes.

First probe the remote HDF5 metadata with:

```bash
bash datasets/zenodo_calochallenge_showers_f64/probe.sh
```

The probe requests only the first 4 MiB of `dataset_2_1.hdf5`, verifies the
HTTP range response and full-object size, then reports the stored `showers`
shape, float width, chunk geometry, and compression filter.  No complete
dataset payload is downloaded at this stage.

The validated source uses a `391 x 51` chunk layout.  The bounded selection is
the first ten complete row-chunk bands: 3,910 complete events, each containing
6,480 native float64 cell energies.  This produces 25,336,800 values and
202,694,400 primary bytes.

Acquire only the HDF5 metadata nodes and compressed chunks required for that
selection, then build and independently verify the samples:

```bash
bash datasets/zenodo_calochallenge_showers_f64/download.sh
bash datasets/zenodo_calochallenge_showers_f64/build.sh
bash datasets/zenodo_calochallenge_showers_f64/verify.sh
```

The downloader follows the source HDF5 chunk B-tree, coalesces nearby source
ranges, and enforces a 200 MB downloaded-range ceiling.  It does not fetch the
complete 1.36 GB HDF5 object.  The decoder uses only Python's standard library
and zlib.

The validated build emits 3,910 distinct event samples containing 25,336,800
values (202,694,400 bytes).  Deposited energy is nonnegative and highly sparse:
19,167,727 values, or 75.65%, are exact zeros.  The aggregate decoded-byte
SHA-256 is
`a2a8b302b1a6d2c08df8da9e90a9f0bb034c5d0a045917f5162c61c0532184d0`.

Dataset 1 is not used for training: its natural photon and pion events contain
only 368 and 533 values respectively, below the repository's 1,000-value
median-sample floor.  Its previously downloaded files remain useful evidence
that the CaloChallenge HDF5 arrays are native float64.
