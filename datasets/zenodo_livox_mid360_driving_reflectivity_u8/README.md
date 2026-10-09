# Livox MID-360 Driving SLAM Test: Per-Point Reflectivity (uint8)

This recipe collects per-point laser return reflectivity from a Livox MID-360
solid-state lidar. The MID-360 scans a non-repetitive rosette pattern. The
source is Kenji Koide's (AIST) "Driving SLAM Test with Livox MID360" rosbag2
recording: Zenodo record 14841855, recorded 2024-04-16, 277 s long. The recipe
takes all 2,772 `/livox/lidar` frames (about 10 Hz) and emits one uint8 sample
per frame, one byte per point slot, in native scan order.

- Source: <https://zenodo.org/records/14841855>, a single file
  `rosbag2_2024_04_16-14_17_01.zip` of 517,088,133 bytes with MD5
  `0836c50859bb1af591966b69da166186`.
- License: CC BY 4.0. The Zenodo record API reports
  `"license": {"id": "cc-by-4.0"}`, open access. `download.sh` re-checks the
  license and the pinned size/MD5 against the live record JSON.
  **Attribution:** Koide, Kenji (AIST), *Driving SLAM Test with Livox MID360*,
  Zenodo, doi:10.5281/zenodo.14841855.

## Source format and decode path

The zip holds `metadata.yaml` and one rosbag2 SQLite database
(`..._0.db3`, 1,468,932,096 bytes). `metadata.yaml` reports storage
`sqlite3`, no bag compression, and 2,772 `/livox/lidar`
`sensor_msgs/msg/PointCloud2` messages next to 55,435 `/livox/imu` messages.
`download.sh` checks these facts.

1. `zipfile` extracts the db3 to `$DATA_DIR/extracted/<id>/build/`, checking
   the CRC. This takes about 1.5 GB of temporary space, and the extract is
   deleted afterwards. The SQLite pages are not parsed by hand, because
   overflow pages are not contiguous.
2. The stdlib `sqlite3` module runs
   `messages JOIN topics WHERE name='/livox/lidar' ORDER BY timestamp, id`.
3. Each message is parsed as CDR little-endian (`00 01 00 00`), with 4-byte
   alignment relative to the end of the encapsulation header. The parser
   reads the header (stamp, `frame_id` `livox_frame`), height, width and the
   **fields array**, then is_bigendian, point_step, row_step, data and
   is_dense, and requires the message to end exactly there.
4. The recipe requires `point_step == 26` and an `intensity` field of type
   FLOAT32 (7) at offset 12. This is the livox_ros_driver2 layout: x, y, z,
   intensity float32 @0/4/8/12; tag uint8 @16; line uint8 @17; timestamp
   float64 @18. It also requires height 1 and
   `len(data) == row_step == 26 * width`.
5. Every intensity must be exactly one of the 256 float32 bit patterns of the
   integers 0..255. NaN, fractions, values outside the range and `-0.0` are
   fatal for the whole build. The uint8 cast is therefore lossless: the sensor
   reports reflectivity as one byte, and the driver widens it to float32.

Not emitted: x/y/z, the per-point timestamp, `tag` (return/noise flags),
`line` (laser line 0..3), and the IMU and other topics.

`verify.sh` re-does all of this independently. It re-extracts the db3,
resolves the topic id, and parses the CDR with its own offset arithmetic. It
decodes every point with `struct.iter_unpack('<3ffBBd')` and compares the
result byte-for-byte with each sample.

## Scan order, no-return slots and the zero fraction

The MID-360 driver publishes a fixed cadence of point slots: 4 laser lines
fire together, so points come in groups of 4 with `line` 0,1,2,3. Frames in
the full build held 19,776 to 20,256 points (multiples of 96, mostly 19,968). Slots
with no return are kept in place with x=y=z=0 and intensity 0. The 13 frames
probed before the download, all from the start of the bag, had about 28%
no-return slots. The full recording has many more: the platform drives through
open areas where much of the field of view has no return within range.

- No-return slots: 47.9% overall. Per frame: min 18.1%, median 47.1%,
  90th percentile 67.7%, max 75.6%.
- Zero values: 48.8% overall (no-return slots plus a few returned points
  with reflectivity 0). Per frame: min 18.6%, median 47.8%, max 77.0%.
- The most common value is always 0. It covers at most 77.0% of a frame,
  just under the 80% rejection threshold in `verify.sh`, which is close to
  the largest value observed.
- Returned points are mostly low: the median non-zero value is 19, 85% of
  non-zero values are 50 or below, and only 0.14% of all values are
  retro-reflective (151-255). Per frame, the data holds 95 to 188 distinct
  values (median 134), and all 256 values occur overall.

The recipe does not filter no-return slots. Removing them would break the
native fixed-cadence scan order and invent a local selection. The zeros are what
the sensor driver emits, at sensor-determined positions that follow the scene
geometry (sky and open space), so they are part of the material. They are,
however, a large share of the bytes: a compressor gets a lot from them, and the
judge should weigh that. The per-frame no-return and zero fractions are in
the index and in `filtered/<id>/build_stats.json`.

## Scope and homogeneity

The output comes from one sensor unit, one driver layout (point_step 26),
one drive and one quantity on one 0–255 lattice. It covers every lidar frame
in the record: 2,772 samples of about 20 k values each, about 55 MB in total.
The record holds only this one bag. These other Koide datasets are
deliberately **not** mixed in, because they are different regimes or storage
formats:
- the Livox Avia bags (ROS1 CustomMsg, a different sensor; Zenodo 7641866 and
  6864654);
- the MID-360 mcap tarball (Zenodo 21486938).

## Novelty

`novelty.py` (URL plus the terms livox, mid360, mid-360, rosbag2) found no
match in the recipes, the registry or downstream; only the Zenodo host is
shared. The nearest local 8-bit lidar family is
`boreas_velodyne_alpha_prime_intensity_u8`: a spinning 128-beam Velodyne,
points in interleaved firing order, only returned points kept. This recipe
differs in three ways:
- a different instrument line (Livox solid-state rosette scan);
- a different reflectivity scale (Livox 0–150 diffuse, 151–255 retro, versus
  Velodyne's 0–100 / 101–255);
- a different ordering (4-line groups along rosette petals, with in-place
  no-return slots).

The airborne LAS 8-bit fields (scan angle, classification, return number) are
other quantities. Whether this lands far enough from Boreas is left to the
zlsim gate.

## Realized output

- 2,772 samples (every /livox/lidar message), 55,440,864 bytes, uint8, one
  value per point slot.
- Points per frame: 19,776 (10 frames), 19,872 (203), 19,968 (1,492),
  20,064 (980), 20,160 (85), 20,256 (2). Median 19,968.
- Zero fraction 48.8% overall and no-return fraction 47.9% (per-frame ranges
  above). The largest per-frame mode fraction is 77.0%.
- 2,649 frames reach a value above 150 and 1,134 reach 255.
- build and verify both run in about 20 s once the db3 is extracted. Both
  delete the 1.47 GB extract.

## Files

- `download.sh`: Zenodo record JSON (license and checksum check), liveness
  range GET, resumable curl of the zip, then size, MD5 and semantic zip check
  (members, metadata.yaml counts, full CRC pass over the db3 member).
- `build.sh` → `scripts/build_samples.py` (helpers in `scripts/livox_bag.py`,
  which has a synthetic CDR + SQLite + zip self-test).
- `verify.sh` → `scripts/verify_samples.py`: independent re-derivation.
