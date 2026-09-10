# Blocked: Kubric MOVi-A optical flow uint16

Date: 2026-09-10

Dataset ID: `kubric_movi_optical_flow_u16`

Status: blocked

## Technical value

MOVi-A contains dense forward and backward optical-flow tensors stored as
native uint16. A width-correct recipe could separate each video's
`delta_row` and `delta_column` components into four homogeneous samples with
shape `24 x 256 x 256`.

This would add a useful 16-bit spatiotemporal motion-field pattern: smooth
object interiors, sharp boundaries, occlusions, temporally coherent motion,
and large static regions. One small validation shard would be sufficient to
produce tens of megabytes of natural samples.

## Metadata findings

The user-run metadata discovery listed 1,616 TFRecord shards under the public
`gs://kubric-public/tfds/movi_a/` prefix, totaling 297,263,841,434 bytes. It
fetched no TFRecord payloads.

The exact 1.0.0 TFDS metadata declares:

- `forward_flow`: 24 x height x width x 2, uint16;
- `backward_flow`: 24 x height x width x 2, uint16; and
- separate two-element float32 range metadata used to map the codes back to
  pixel displacement.

The float32 range vectors are metadata, not substantial training series. The
flow codes themselves are valid prospective uint16 material and would need to
be emitted canonically in little-endian order.

## License investigation

The license-only probe inspected pinned revisions of:

- `google-research/kubric` at
  `61f2422c84bab75006df33c6989e0b483db3ccfe`; and
- `tensorflow/datasets` at
  `0a109f1ec6ca3638db9db97e3fecd809f5fccffa`.

Both repositories declare Apache-2.0 for their source code. Kubric's MOVi
README describes and links the GCS datasets but contains no explicit license
grant for those dataset objects. The exact TFDS `dataset_info.json` documents
also contain no `license` field. TensorFlow Datasets warns generally that its
Apache-2.0 code license does not grant rights to hosted datasets and that users
must establish the dataset license separately.

## Conclusion

The candidate is technically strong but blocked for training use. Public
access, an Apache-licensed generator, and an Apache-licensed loader do not by
themselves establish permission to use the separately hosted MOVi-A data as
training material.

Retry only if Google or the Kubric authors publish an explicit license or
terms statement covering the exact MOVi-A dataset objects. Do not download
TFRecord shards before that evidence exists.
