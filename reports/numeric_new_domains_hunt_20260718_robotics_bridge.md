# Numeric New Domains Hunt: Google Robotics Bridge TFRecord

## Recommendation

Stage `google_robotics_bridge_tfrecord_u8`, using one fixed public Google
Research Robotics BridgeData V2 TFRecord shard.

## Why This Adds New Territory

- Domain: robot manipulation demonstrations / robot-learning trajectories.
- Shape: a large TFRecord shard of serialized RLDS examples, with source
  metadata describing uint8 camera observations and float32 rewards, states,
  actions, and language embeddings.
- Difference from accepted datasets: the catalog has depth-camera rasters and
  many scientific/finance/geospatial tables, but not robot control
  demonstration records.
- Numeric representation: dependency-free TFRecord framing extraction emits a
  large uint8 payload stream plus uint32 record-length and masked-CRC streams.

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

## Script To Run

```bash
bash staging/google_robotics_bridge_tfrecord_u8/download.sh
```

After the download succeeds, build and verify locally:

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

## Acceptance Outcome

The BridgeData V2 TFRecord shard downloaded, built, and verified successfully.

- source shard bytes: 435,280,257
- downloaded bytes including metadata: 435,311,894
- TFRecord records: 30
- payload bytes: 435,279,777
- primary samples: 3
- primary values: 435,279,867
- primary bytes: 435,280,137
- output cap behavior: one fixed shard processed; primary output remained below
  the 1 GB cap
