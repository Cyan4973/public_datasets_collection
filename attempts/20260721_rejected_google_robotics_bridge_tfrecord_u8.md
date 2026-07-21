# Rejected: google_robotics_bridge_tfrecord_u8

Date: 2026-07-21

Status: rejected

Source:
- https://storage.googleapis.com/gresearch/robotics/bridge/0.1.0/bridge-train.tfrecord-00000-of-01024
- https://storage.googleapis.com/gresearch/robotics/bridge/0.1.0/dataset_info.json
- https://storage.googleapis.com/gresearch/robotics/bridge/0.1.0/features.json

Expected value:
- Robot manipulation demonstration trajectories are a useful new domain for the
  corpus.
- The TFDS metadata declares real typed source features, including
  `steps/observation/image` as `uint8` images with shape `480x640x3`, plus
  float32 state, action, reward, and language-embedding tensors.

Rejected shape:
- The active recipe stripped TFRecord framing and emitted one primary sample per
  serialized TFRecord/protobuf payload.
- That fixed an earlier natural-record concatenation error, but the primary
  samples were still serialized container payload bytes rather than decoded
  camera frames or tensors.

Evidence:
- The local build stats showed 30 TFRecord payload samples and 435,279,777
  primary bytes, all from serialized payload records.
- `features.json` declares the meaningful decoded fields.
- A read-only local parse of one payload found feature names such as
  `steps/observation/image`, `steps/observation/state`, and
  `steps/action/world_vector`; the image feature values begin with the PNG magic
  bytes `89 50 4e 47 0d 0a 1a 0a`.

Reason:
- Repository policy requires primary numeric series to be decoded typed values,
  not opaque file-container or serialized payload bytes.
- TFRecord/protobuf payload bytes are not an acceptable `uint8` numeric series,
  even when the underlying payload contains useful numeric tensors.

Retry condition:
- Do not retry this dataset ID as serialized TFRecord bytes.
- Retry only as a decoded successor that extracts documented typed fields from
  the TF Example payloads, such as decoded camera frames.
