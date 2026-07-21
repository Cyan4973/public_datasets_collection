# Google Robotics Bridge TFRecord UInt8

Recipe for one bounded public Google Research Robotics BridgeData V2 TFRecord
shard.

The target material is robot manipulation demonstration data: TFDS/RLDS
examples containing uint8 camera observations and float32 rewards, states,
actions, and language embeddings. This recipe keeps the dependency surface
small by preserving each natural TFRecord record payload as its own primary
sample. TFRecord record lengths and masked CRCs are emitted only as auxiliary
framing metadata; they are not a standalone 32-bit robotics dataset.

Run:

```bash
bash staging/google_robotics_bridge_tfrecord_u8/download.sh
```

Then build and verify locally:

```bash
bash staging/google_robotics_bridge_tfrecord_u8/build.sh
bash staging/google_robotics_bridge_tfrecord_u8/verify.sh
```
