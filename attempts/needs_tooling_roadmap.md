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
- `mitbih_arrhythmia_physionet` has been moved out of `needs_tooling` and into an accepted recipe
- the WFDB parser workflow is now implemented locally and is no longer an open tooling blocker

Expected value:
- Adds ECG waveform families with different record structures
- Unlocks both classic arrhythmia traces and fixed-shape multi-lead records

Acceptance bar:
- Record-level integrity checks in `verify.sh`
- Explicit signal scaling / integer preservation policy
- No ad hoc one-dataset decoder forks

## 3. Raster / Image Decode Workflow

Missing capability:
- None for the current external-registry backlog

Current state:
- `worldclim_tavg_10m` has been moved out of `needs_tooling` and into an accepted recipe
- `davis17_sparse_masks_u8` is blocked by source access from this environment, not by decode logic
- raster tooling is no longer an open blocker for the remaining external-registry backlog

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
1. `Seismic window selection workflow`

Reasoning:
- `EDF` is already done locally
- `WFDB` is already done locally
- `Raster / image` is no longer an open tooling blocker for the current external-registry backlog
- `Seismic window selection` is the remaining open tooling family and depends more on
  acquisition design than pure decode logic
