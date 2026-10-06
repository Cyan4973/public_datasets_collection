# Cartographer 2D Backpack Hokuyo Horizontal Laser Ranges (float32)

Planar laser range profiles from the horizontal Hokuyo UTM-30LX-EW scanner on
Google's Cartographer 2D mapping backpack, recorded while walking the
Deutsches Museum (Munich), 2014-2016. Each sample is one complete recording
session: a row-major `scans x 1079` matrix of little-endian float32 ranges in
metres, decoded from the ROS `sensor_msgs/MultiEchoLaserScan` topic
`horizontal_laser_2d`. The first echo of each beam is kept.

## Source and license

- Inventory and license: `cartographer_ros/docs/source/data.rst`, pinned to
  commit `ef0e971b` (the file's last change, 2018-10-25; identical to master
  on 2026-10-06). The "2D Cartographer Backpack - Deutsches Museum" section
  has its own `License` subsection: *Copyright 2016 The Cartographer Authors.
  Licensed under the Apache License, Version 2.0.* The bag table follows it,
  so the grant covers the bags, not just the docs code.
- Objects: `https://storage.googleapis.com/cartographer-public-data/bags/backpack_2d/<bag>.bag`,
  anonymous GCS. The bucket listing is denied, so the bag list comes from
  data.rst, which lists 56 backpack_2d bags.

## Selection (16 of 56 sessions)

Each session is ~160 KB/s of primary float32. All 56 sessions together come to
~7.5 GB, well over the 1 GB cap. `scripts/select_sources.py` (re-run by
`discover.sh`) applies a fixed rule to the metadata table:

1. Exclude the three bags data.rst flags with gaps in the laser data
   (`b2-2015-05-12-12-29-05`, `b2-2015-05-12-12-46-34`,
   `b2-2016-02-02-14-01-56`). `b0-2014-07-21-12-49-19` is flagged only for
   "1 gap in vertical laser data". The vertical scanner isn't collected, so it
   stays eligible, and build and verify reject any horizontal gap above 1 s.
2. Take the shortest eligible session for each backpack unit (b0, b1, b2) and
   each floor (OG, EG, UG).
3. Add the remaining eligible sessions shortest-first while the primary output
   stays at or below 950,000,000 bytes.

Result: 16 sessions (b0 x7, b1 x1, b2 x8; floor OG x14, EG x1, UG x1),
209,373 scans, 225,913,467 values, 903,653,868 bytes. Sessions range from
5,522 to 26,053 scans (23.8 MB to 112.4 MB); the median is 12,426 scans.
Download: 1,470,431,881 bytes. About 60% of each bag is IMU and
vertical-laser data that isn't kept; bz2 chunks interleave all topics, so no
leaner byte range exists.

`discover.sh` fetches, for each of the 56 bags, the HEAD metadata, the first
8 KB (bag header with `index_pos`), and the index section (connection plus
chunk-info records). It needs about 12 MB of metadata in total and no message
payloads. That gives exact per-topic message counts, so `sources.tsv` pins
size, MD5, CRC32C, GCS generation, `index_pos`, chunk count and the exact
horizontal scan count for every selected bag.

## Decoding

ROS bag v2.0 is parsed with the standard library only (`scripts/cartographer_hokuyo.py`):

- records = `uint32 header_len`, `name=value` header fields, `uint32 data_len`, data
- op 3 bag header (`index_pos`, `conn_count`, `chunk_count`)
- op 5 chunks (`bz2`, uncompressed size checked); inside them, op 7
  connection records map connection id to topic/type/md5, and op 2 message
  records carry serialized messages
- op 4 index-data records follow each chunk; ops 7 and 6 (chunk info) form the
  index section after `index_pos`

Each `MultiEchoLaserScan` message is: Header (seq, stamp, frame_id), 7 float32
fields (angle_min, angle_max, angle_increment, time_increment, scan_time,
range_min, range_max), `uint32` beam count, then per beam a `uint32` echo
count and that many float32 echoes, then the same layout for intensities.
The recipe copies the 4 bytes of `echoes[0]` per beam unchanged.

`build.sh` walks every chunk in file order. `verify.sh` takes a separate
path: it goes chunk-info, then chunk, then index-data offsets, decodes with a
separate float-based decoder, and compares every scan byte-for-byte with the
emitted sample. It also re-checks hashes, counts, value policy, floors, cap
and manifest scope. Both decoders were self-tested on synthetic bags
containing bz2 and uncompressed chunks, interleaved topics, and 1-3-echo and
zero-echo beams; the output was byte-exact against the generator. They were
also cross-checked against each other on real chunks from b0, b1 and b2 bags.

## Homogeneity

One sensor model at one mounting (horizontal Hokuyo UTM-30LX-EW), one
platform design, one site, one unit (m). Geometry is identical in all
209,373 built scans of b0, b1 and b2: angle_min = -2.35183 rad, angle_max =
+2.35183 rad, increment = 0.0043633 rad (0.25 deg), 1079 beams, scan_time
0.025 s, range_min 0.023 m, range_max 60.0 m. The build asserts these
float32 bit patterns in every scan. Only `time_increment` (per-beam timing
metadata, not collected) changes: 1.7361e-05 s in every 2014 session (b0, b1
and b2) and 1.7329e-05 s in the three 2015-2016 b2 sessions, so it tracks
recording date rather than backpack unit. The vertical push-broom laser
uses a different mounting and view, so it isn't collected.

## Things to know

- **Width honesty.** The Hokuyo outputs integer millimetres, and the recording
  driver stored float32 metres, so every value is `float32(n/1000)` with
  `n` an integer (verify checks this lattice). These are the published
  upstream float32 objects, copied bit-for-bit, not a local widening. The
  same lattice re-coded as uint16 mm would fit in 16 bits; the recipe does
  not re-code.
- **Sentinel.** `60.0` (= range_max) is the driver's no-return/out-of-range
  value: 21,582,485 values, 4.0-24.1% per session, 9.55% overall. It's kept
  as-is (not NaN) and counted per sample (`range_max_sentinel_count` in the
  index). Verify re-counts it and rejects any session above 50%.
- **Zero-echo beams.** A LaserEcho with no echoes has no source range. It
  becomes canonical quiet NaN (0x7FC00000) and is counted per sample
  (`zero_echo_nan_count`): 157 values in 10 of 16 sessions (max 55), 7e-7 of
  the total. Verify requires the NaN count to equal the re-derived zero-echo
  count.
- **Multi-echo.** 2.9-5.9% of beams per session carry 2-3 echoes; only the
  first echo is kept.
- Natural record = one recording session (one `.bag`). A single scan is one
  frame of a continuous ~37 Hz stream with no separate upstream file, the
  same framing as accepted recording-level recipes such as EIT frame
  recordings and ADCP ensemble recordings. Samples are large (24-112 MB) and
  are not sharded.

## Realized build

16 samples, 209,373 scans, 225,913,467 float32 values, 903,653,868 bytes.
Every finite value is on the float32(mm/1000) lattice (0 off-lattice). Range
0.026-60.0 m. 28k-43k distinct values per session. Max inter-scan gap
0.068 s. Build and verify each take about 50 s with 16 workers.

## Running

```bash
bash staging/cartographer_backpack2d_hokuyo_ranges_f32/download.sh   # ~1.47 GB
bash staging/cartographer_backpack2d_hokuyo_ranges_f32/build.sh      # WORKERS=16 default
bash staging/cartographer_backpack2d_hokuyo_ranges_f32/verify.sh
```

All scripts honour `DATA_DIR` (default `.data`, relative to the repo root or
absolute) and log to `$DATA_DIR/logs/cartographer_backpack2d_hokuyo_ranges_f32/`.
