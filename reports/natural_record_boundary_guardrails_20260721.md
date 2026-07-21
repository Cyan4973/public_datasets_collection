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

These accepted recipes are known legacy exceptions and should be repaired or
retired instead of copied as patterns:

- `google_quickdraw_bitmap_classes_u8`: groups independent 28x28 drawings into
  class-level bitmap stacks

`mnist_px_u8` has been retired and rejected: individual MNIST images are only
784 uint8 values, and class-level concatenation is not acceptable.

`fmnist_px_u8` has been retired and rejected for the same reason: individual
Fashion-MNIST images are only 784 uint8 values, and class-level concatenation is
not acceptable.

`google_robotics_bridge_tfrecord_u8` was repaired separately: each TFRecord
payload record is now a primary sample, and TFRecord lengths/CRCs are auxiliary
metadata only.
