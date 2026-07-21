# Needs Tooling: google_robotics_bridge_image_frames_u8

Date: 2026-07-21

Status: needs_tooling

Source:
- https://storage.googleapis.com/gresearch/robotics/bridge/0.1.0/bridge-train.tfrecord-00000-of-01024
- https://storage.googleapis.com/gresearch/robotics/bridge/0.1.0/features.json

Expected value:
- Decoded BridgeData V2 camera observations would add robot-learning visual
  trajectories as a real `uint8` image-frame corpus.
- The already downloaded shard contains 30 episodes and 1006 steps.
- Decoding all `steps/observation/image` frames to `480x640x3` uint8 samples
  would produce about 927,129,600 primary bytes, under the 1 GB cap.

Intended accepted shape:
- One decoded camera frame per primary sample.
- `numeric_kind = "uint"`, `bit_width = 8`, `sample_shape = [480, 640, 3]`.
- Natural record kind should describe a decoded Bridge observation frame, not a
  TFRecord payload, shard, or episode-level byte stream.
- TFRecord framing, protobuf field names, PNG source sizes, episode IDs, and
  step indexes may be auxiliary metadata only.

Missing capability:
- A reproducible local decoder path for TF Example payloads and PNG image
  values.
- The current environment does not provide TensorFlow, TensorFlow Datasets,
  protobuf Python bindings, Pillow, or NumPy.

Reason not accepted now:
- Implementing or vendoring a PNG decoder locally would be disproportionate.
- Accepting serialized TFRecord/protobuf bytes as a shortcut would violate the
  decoded typed-value rule.

Retry condition:
- Retry once the repository has an approved dependency or reusable local tooling
  path for TF Example/protobuf extraction and PNG frame decoding.
