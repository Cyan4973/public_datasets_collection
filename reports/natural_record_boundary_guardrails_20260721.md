# Natural Record Boundary Guardrails

## Purpose

This repository should not accept recipes that concatenate independent natural
records into larger physical samples just to clear acceptance floors. If a
natural record is small, the dataset is small-record material; the recipe must
not hide that fact by grouping records by class, prompt, split, shard, source
file, or archive.

## Enforced Rules

`tools/check_repo_hygiene.py` now checks accepted dataset manifests for high-risk
blind-concatenation language. For new or touched accepted manifests, it also
requires every primary series to declare a specific `natural_record_kind` and
rejects generic aggregation names such as class stacks, row streams, contiguous
streams, payload streams, or shard payloads.

The intended choices are:

- emit each natural record as its own primary sample
- explicitly document and review a floor waiver for naturally small records
- reject or retire the dataset

## Known Legacy Violations

No accepted recipe is currently exempted from the blind-concatenation guardrail.

`mnist_px_u8` has been retired and rejected: individual MNIST images are only
784 uint8 values, and class-level concatenation is not acceptable.

`fmnist_px_u8` has been retired and rejected for the same reason: individual
Fashion-MNIST images are only 784 uint8 values, and class-level concatenation is
not acceptable.

`google_quickdraw_bitmap_classes_u8` has been retired and rejected for the same
reason: individual Quick, Draw! bitmap drawings are only 784 uint8 values, and
prompt-class concatenation is not acceptable.

`google_robotics_bridge_tfrecord_u8` fixed the earlier blind-concatenation
mistake by emitting one TFRecord payload per sample, but it still preserved
serialized TFRecord/protobuf payload bytes as the primary `uint8` material. It
has therefore been retired and rejected under the decoded typed-value rule. A
future BridgeData recipe must decode documented fields, such as camera frames,
before promotion.
