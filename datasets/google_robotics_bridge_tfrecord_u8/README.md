# Google Robotics Bridge TFRecord UInt8

Candidate recipe for one bounded public Google Research Robotics BridgeData V2
TFRecord shard.

The target material is robot manipulation demonstration data: TFDS/RLDS
examples containing uint8 camera observations and float32 rewards, states,
actions, and language embeddings. This recipe keeps the dependency surface
small by preserving the natural TFRecord record payload bytes and record
framing metadata as numeric streams.

Run:

```bash
bash staging/google_robotics_bridge_tfrecord_u8/download.sh
```

Then build and verify locally:

```bash
bash staging/google_robotics_bridge_tfrecord_u8/build.sh
bash staging/google_robotics_bridge_tfrecord_u8/verify.sh
```
