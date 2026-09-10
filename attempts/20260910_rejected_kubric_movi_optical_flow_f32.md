# Rejected: Kubric MOVi-A optical flow float32

Date: 2026-09-10

Dataset ID: `kubric_movi_optical_flow_f32`

Status: rejected

## Intended value

MOVi-A contains synthetic rigid-body videos with dense forward and backward
optical flow. Separating horizontal and vertical displacement would provide a
useful spatiotemporal motion-field shape with smooth interiors, sharp object
boundaries, occlusions, and large near-static regions.

## Metadata-only discovery

The user-run discovery listed the public
`gs://kubric-public/tfds/movi_a/` prefix and fetched only five small TFDS
metadata documents. It downloaded no TFRecord payloads.

The listing contained:

- 1,616 TFRecord shards;
- 297,263,841,434 aggregate shard bytes;
- 128x128 and 256x256 configurations;
- train and validation splits; and
- generation and checksum metadata for every object.

## Width finding

The exact version-1.0.0 TFDS metadata declares both `forward_flow` and
`backward_flow` as 24-frame `uint16` tensors with two components per pixel.
Per-clip `forward_flow_range` and `backward_flow_range` metadata are float32
two-element vectors. The documented conversion to pixel displacement is:

```text
flow = encoded_uint16 / 65535 * (max_value - min_value) + min_value
```

Consequently, emitting full float32 flow fields would expand values whose
stored numerical representation contains only 16 bits. The tiny float32 range
vectors are not substantial natural samples. This source is therefore not a
valid new 32-bit family.

## License finding

Neither exact `dataset_info.json` document contains a `license` field. The
metadata points to the Kubric source repository and includes a citation, but a
code-repository license must not be inferred to license separately hosted
dataset objects.

## Conclusion

Reject this source for `kubric_movi_optical_flow_f32`. Do not download a shard
or implement TFRecord decoding for the 32-bit proposal.

A separately named uint16 successor could be reconsidered only if explicit
license evidence for the exact MOVi-A data objects is established. Such a
successor must preserve the native uint16 flow codes in little-endian form and
keep horizontal/vertical and forward/backward fields separate.
