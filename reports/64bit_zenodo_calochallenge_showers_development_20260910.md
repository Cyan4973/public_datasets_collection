# CaloChallenge Dataset 2 electron showers float64

Date: 2026-09-10

Dataset ID: `zenodo_calochallenge_showers_f64`

Status: accepted

## Motivation

This family adds simulated high-energy-particle calorimeter showers.  Each
natural record is one sparse deposited-energy pattern over 6,480 detector
cells, unlike an ordinary image, scalar timeline, table column, or dense field
snapshot.  The source was published specifically for machine-learning research
on fast detector simulation.

## Provenance and license

- Zenodo record: `6366271`
- DOI: `10.5281/zenodo.6366271`
- Title: *Fast Calorimeter Simulation Challenge 2022 - Dataset 2*
- License declared by the exact record: CC BY 4.0
- Selected source: `dataset_2_1.hdf5`
- Full source size: 1,356,475,617 bytes
- Full source MD5: `e590333e9a2da51b258288d74bd8357a`

The source contains 100,000 GEANT4-simulated single-electron showers with
incident energies sampled log-uniformly from 1 GeV to 1 TeV.  The documented
detector has 45 layers, with 9 radial and 16 angular readout cells per layer.

## Width and layout findings

The root HDF5 `showers` dataset is:

- shape `100000 x 6480`;
- native little-endian IEEE-754 float64;
- chunked as `391 x 51`; and
- compressed with the HDF5 DEFLATE filter.

The separate `incident_energies` dataset is excluded.  It is a different
physical quantity and is not needed to decode the shower-cell values.

The earlier Dataset 1 float32 proposal was superseded.  Dataset 1 is also
below the natural-record median floor because its independent photon and pion
showers contain only 368 and 533 values respectively.  Dataset 2 contains
6,480 values per independent shower and therefore clears the floor naturally.

## Bounded acquisition and decoding

The complete Dataset 2 training file would decode to 5.184 GB, beyond the
repository cap.  The recipe selects the first ten complete 391-event HDF5
row-chunk bands, events 0 through 3909.  It follows the source HDF5 v1 raw-data
chunk B-tree, range-fetches only required metadata nodes and compressed chunks,
and coalesces nearby source spans.

The user-run acquisition fetched 52,691,462 data-range bytes rather than the
complete 1.36 GB object.  A standard-library decoder inflates each chunk with
zlib, reconstructs source row-major order, removes only the HDF5 edge-chunk
padding beyond logical column 6479, and emits one complete event per sample.
No arithmetic conversion, byte swapping, interpolation, normalization, or
event concatenation occurs.

## Accepted output

- Samples: 3,910 complete electron showers
- Values per sample: 6,480
- Bytes per sample: 51,840
- Total values: 25,336,800
- Total bytes: 202,694,400
- Minimum: 0.0
- Maximum: 4248.93169359166
- Exact-zero values: 19,167,727 (75.65%)
- Aggregate decoded-byte SHA-256:
  `a2a8b302b1a6d2c08df8da9e90a9f0bb034c5d0a045917f5162c61c0532184d0`

All event payloads are finite, nonnegative, nonconstant, and pairwise distinct.
Verification independently retraverses the HDF5 chunk tree, re-inflates every
selected chunk, reconstructs all events, and byte-compares every emitted
sample.

