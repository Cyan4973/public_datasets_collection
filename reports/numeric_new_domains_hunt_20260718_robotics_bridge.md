# Numeric New Domains Hunt: Google Robotics Bridge TFRecord

Historical status: rejected on 2026-07-21.

This report is retained as history. The recommended recipe fixed a
record-boundary issue but still used serialized TFRecord/protobuf payload bytes
as the primary `uint8` material. That is not an acceptable decoded numeric
series. Retry BridgeData V2 only as a decoded successor, for example by
extracting `steps/observation/image` into real `480x640x3` uint8 frame samples.

## Historical Recommendation

The obsolete recommendation was to stage `google_robotics_bridge_tfrecord_u8`,
using one fixed public Google Research Robotics BridgeData V2 TFRecord shard.

## Why This Adds New Territory

- Domain: robot manipulation demonstrations / robot-learning trajectories.
- Shape: 30 variable-size TFRecord record payloads from one serialized RLDS
  shard, with source metadata describing uint8 camera observations and float32
  rewards, states, actions, and language embeddings.
- Difference from accepted datasets: the catalog has depth-camera rasters and
  many scientific/finance/geospatial tables, but not robot control
  demonstration records.
- Rejected numeric representation: dependency-free TFRecord framing extraction
  emitted one primary uint8 sample per TFRecord payload record. The uint32
  record-length and masked-CRC streams were auxiliary TFRecord framing metadata,
  not a standalone 32-bit robotics dataset.

## Materiality

The selected object,
`bridge-train.tfrecord-00000-of-01024`, has an observed HTTP
`Content-Length` of 435,280,257 bytes. It is large enough to be useful while
remaining comfortably below the repository's 1 GB per-dataset download cap.

The recipe enforces:

- source shard cap: 500,000,000 bytes
- total download cap: 510,000,000 bytes
- source shard floor: 400,000,000 bytes
- TFRecord payload floor: 390,000,000 bytes
- record floor: 16 records
- primary-output hard cap: 1,000,000,000 bytes

## Obsolete Script

```bash
bash staging/google_robotics_bridge_tfrecord_u8/download.sh
```

After the download succeeded, the obsolete local build and verify commands were:

```bash
bash staging/google_robotics_bridge_tfrecord_u8/build.sh
bash staging/google_robotics_bridge_tfrecord_u8/verify.sh
```

## Rejected Candidates In This Pass

- Open Food Facts would have added packaged-food nutrition, but the static
  export host is blocked from this environment and older repo notes only found
  a tiny OpenFoodFacts API sample.
- GH Archive would have added software event telemetry, but `data.gharchive.org`
  is blocked here and was already rejected in a previous pass.
- UCI Online Retail II would add retail transaction logs, but the UCI archive
  endpoint is currently blocked from this environment.
- FEC bulk campaign-finance files remain blocked from this environment and were
  already noted as rejected in an earlier hunt.

## Historical Acceptance Outcome

The BridgeData V2 TFRecord shard downloaded, built, and verified successfully
under the obsolete serialized-payload recipe.

- source shard bytes: 435,280,257
- downloaded bytes including metadata: 435,311,894
- TFRecord records: 30
- payload bytes: 435,279,777
- primary samples: 30
- primary values/bytes: 435,279,777
- auxiliary framing samples: 2
- auxiliary framing values: 90
- auxiliary framing bytes: 360
- output cap behavior: one fixed shard processed; primary output remained below
  the 1 GB cap

## Clarification

There is no accepted dataset named `robotics_bridge_container_u32`. The two
uint32 streams in this recipe are TFRecord container metadata: 30 payload-length
values and 60 masked-CRC values. They exist only to document framing and should
not be counted as independent robotics-domain 32-bit series.

The original accepted recipe briefly represented the 30 payload records as one
concatenated primary byte stream. That was corrected by emitting each TFRecord
payload as its own sample, but this was still not enough: the payloads remained
serialized TFRecord/protobuf bytes rather than decoded camera frames or tensors.
