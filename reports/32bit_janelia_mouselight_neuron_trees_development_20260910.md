# Janelia MouseLight neuron tree fields 32-bit

Date: 2026-09-10

Dataset ID: `janelia_mouselight_neuron_trees_32bit`

Status: accepted

## Motivation

This family adds irregular rooted-tree morphology from reconstructed mouse
neurons. Its numerical structure is distinct from point clouds, linear
trajectories, raster images, dense volumes, and ordinary graph edge lists:
node order follows long branching neurites, while parent references encode the
tree explicitly.

Every source field remains homogeneous. X, Y, and Z coordinates are separate
float32 samples, and parent references are separate int32 samples. Sequential
node IDs, low-cardinality type codes, and constant or nearly binary radii are
excluded.

## Provenance and license

- Provider: Janelia Research Campus MouseLight project
- Distribution: `janelia-mouselight-imagery` AWS Open Data bucket
- AWS registry entry: `datasets/janelia-mouselight.yaml` at commit
  `e4a69a3dfa44fc2237ade6f35393c960383964d0`
- License: Creative Commons Attribution 4.0 International
- Selected source: 320 completed consensus/dendrite SWC objects
- Total source size: 108,215,773 bytes

The authoritative AWS registry describes the bucket as MouseLight imagery and
neuron annotations and explicitly applies CC BY 4.0. Each source is pinned by
object key, byte size, S3 ETag/MD5, SHA-256, and last-modified timestamp.

## Selection and validation

The complete bucket inventory contained 1,638 consensus axons and 1,626
dendrites. The bounded recipe selects 256 axons and 64 dendrites at even
size-rank intervals among canonical SWCs of at least 50,000 source bytes. This
retains broad size diversity without requiring the entire 530 MB canonical
collection.

Every selected SWC must have exactly seven columns, sequential node IDs from
one, exactly one root, and only backward parent references to existing nodes.
Coordinates and radii must be finite and radii nonnegative. Coordinate samples
must be nonconstant, parent samples nondegenerate, and duplicate outputs are
rejected within each series.

## Accepted output

- Source trees: 320 (256 consensus axons and 64 dendrites)
- Nodes: 1,947,050
- Samples: 1,280
- Values: 7,788,200
- Bytes: 31,152,800
- Sample lengths: 944 through 77,521 values
- Median sample length: 3,465.5 values
- Aggregate decoded-byte SHA-256:
  `13735f2ceb37b9a0b72e6c98b92961b06b47b7c76485b79fb839ae38d631b9b9`

Published decimal coordinates are rounded once to IEEE-754 float32. Parent
identifiers are represented exactly as signed int32. Every output is
serialized explicitly in little-endian order, and verification reparses all
320 pinned source files and byte-compares all generated samples.
