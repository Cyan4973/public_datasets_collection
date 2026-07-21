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
- None for the current external-registry backlog

Current state:
- `seismic_waveform_i32` has been moved out of `needs_tooling` and into an accepted recipe
- the fixed 12-window IRIS selection is now implemented locally
- seismic window selection is no longer an open tooling blocker for the current external-registry backlog

## 5. TFRecord / RLDS Image Decode Workflow

Missing capability:
- Reproducible TF Example/protobuf feature extraction from local TFRecord shards
- PNG frame decoding for TFDS image features
- Sample-index helpers that preserve decoded observation-frame boundaries

Unblocked datasets:
- [google_robotics_bridge_image_frames_u8](./20260721_needs_tooling_google_robotics_bridge_image_frames_u8.md)

Current state:
- `google_robotics_bridge_tfrecord_u8` has been rejected because it preserved
  serialized TFRecord/protobuf payload bytes as primary `uint8` samples.
- The BridgeData V2 source remains valuable, and the local shard has enough
  decoded image material to satisfy the corpus floor while staying below 1 GB.

Expected value:
- Adds robot-learning visual observation frames from manipulation trajectories
- Avoids accepting TFRecord, protobuf, or PNG container bytes as a shortcut

Acceptance bar:
- Decode documented TFDS/RLDS fields from local files only
- Emit one decoded `480x640x3` uint8 camera frame per primary sample
- Keep TFRecord framing and protobuf/image-container metadata auxiliary only
- Verify frame shape, count, byte total, and non-degenerate pixel content

## Priority

Recommended implementation order:
1. TFRecord / RLDS image decode, if robot-learning visual trajectories remain a
   desired domain

Reasoning:
- `EDF` is done locally
- `WFDB` is done locally
- `Raster / image` is no longer an open tooling blocker for the current external-registry backlog
- `Seismic window selection` is no longer an open tooling blocker for the current external-registry backlog
- BridgeData V2 is valuable enough to revisit, but only with real decoding
  rather than serialized payload bytes
