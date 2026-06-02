# Needs-Tooling Roadmap

This file groups `needs_tooling` attempts by shared missing capability.

The goal is to turn "7 blocked datasets" into a smaller set of concrete tool
families to implement, review, and retire systematically.

## 1. EDF Parser Workflow

Missing capability:
- Reusable stdlib-only EDF header parsing
- Signal block decoding
- Channel selection helpers

Current state:
- `eeg_physionet` has been moved out of `needs_tooling` and into an accepted recipe
- `chbmit_physionet` has been moved out of `needs_tooling` and into an accepted recipe
- the EDF parser workflow is now implemented locally and is no longer an open tooling blocker

Expected value:
- Adds biomedical multi-channel waveform shapes
- Unlocks long-form EEG sequences from PhysioNet
- Makes the remaining EDF work narrower and better-bounded than before

Acceptance bar:
- Deterministic EDF parsing from local files only
- Channel/sample-count validation in `verify.sh`
- Clear missing-value and scaling policy in manifests

## 2. WFDB Parser Workflow

Missing capability:
- Reusable WFDB record parsing
- MIT-BIH 212 decode support
- Multi-file record handling and validation

Unblocked datasets:
- [mitbih_arrhythmia_physionet](./20260601_needs_tooling_mitbih_arrhythmia_physionet.md)

Current state:
- `ptbxl_physionet` has been moved out of `needs_tooling` and into an accepted recipe
- the remaining WFDB-gated dataset is:
  - [mitbih_arrhythmia_physionet](./20260601_needs_tooling_mitbih_arrhythmia_physionet.md)

Expected value:
- Adds ECG waveform families with different record structures
- Unlocks both classic arrhythmia traces and fixed-shape multi-lead records

Acceptance bar:
- Record-level integrity checks in `verify.sh`
- Explicit signal scaling / integer preservation policy
- No ad hoc one-dataset decoder forks

## 3. Raster / Image Decode Workflow

Missing capability:
- Reviewed raster decode path for GeoTIFF
- Reviewed PNG label-mask decode path

Unblocked datasets:
- [worldclim_tavg_10m](./20260601_needs_tooling_worldclim_tavg_10m.md)
- [davis17_sparse_masks_u8](./20260601_needs_tooling_davis17_sparse_masks_u8.md)

Expected value:
- Adds gridded climate rasters
- Adds segmentation-mask numeric label maps

Acceptance bar:
- Deterministic decode from local files only
- Explicit numeric-value preservation policy
- No third-party Python dependency requirement

## 4. Seismic Window Selection Workflow

Missing capability:
- Reusable event-window selection helper for IRIS imports
- Stable parameterization for reproducible waveform-window acquisition

Unblocked datasets:
- [seismic_waveform_i32](./20260601_needs_tooling_seismic_waveform_i32.md)

Expected value:
- Adds seismic waveform counts, which are numerically and structurally unlike
  the current corpus

Acceptance bar:
- Deterministic window selection recorded in the manifest
- Clear provenance for each selected event/window
- Local validation of sample counts and integer preservation

## Priority

Recommended implementation order:
1. `WFDB parser workflow`
2. `Raster / image decode workflow`
3. `Seismic window selection workflow`

Reasoning:
- `EDF` is already done locally
- `WFDB` unlocks 2 datasets with one tooling family
- `Raster / image` unlocks 2 datasets but likely has a wider parser surface
- `Seismic window selection` unlocks only 1 dataset and depends more on
  acquisition design than pure decode logic
