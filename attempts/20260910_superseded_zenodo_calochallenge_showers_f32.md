# CaloChallenge shower float32 attempt superseded

Date: 2026-09-10

Candidate ID: `zenodo_calochallenge_showers_f32`

Status: `superseded`

Replacement: `zenodo_calochallenge_showers_f64`

## Source checked

- Fast Calorimeter Simulation Challenge 2022 Dataset 1
- Zenodo record `8099322`
- DOI `10.5281/zenodo.8099322`
- Exact record license: CC BY 4.0
- Files inspected:
  - `dataset_1_photons_1.hdf5`
  - `dataset_1_pions_1.hdf5`

## Finding

Both root HDF5 datasets, `incident_energies` and `showers`, use native
little-endian IEEE-754 float64 elements.  They are chunked and DEFLATE
compressed; they are not float32 arrays.  Narrowing them would discard the
source representation and is not an acceptable width classification.

Dataset 1 also fails the natural-record median floor for training: one
independent photon shower has 368 values and one independent charged-pion
shower has 533 values, both below the required 1,000 values.  Treating an
entire HDF5 training split as one sample would concatenate many independent
simulation events and violate the sample-boundary rule.

## Successor

The accepted-width successor uses Dataset 2, where every independent electron
shower contains 6,480 native float64 detector-cell energies.  A bounded HTTP
range selection retains 3,910 complete events while avoiding acquisition of
the complete 1.36 GB source object.

Do not retry these Dataset 1 files as float32.  Use
`zenodo_calochallenge_showers_f64` for the native-width, above-floor material.
