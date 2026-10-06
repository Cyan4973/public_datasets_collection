# Cartographer 2D backpack Hokuyo horizontal laser range float32 development

## Outcome

Accepted `cartographer_backpack2d_hokuyo_ranges_f32`: first-echo range profiles in metres from the horizontal Hokuyo UTM-30LX-EW planar laser scanner on Google's Cartographer 2D mapping backpack, recorded while walking the Deutsches Museum (Munich), 2014-2016.

This is the first planar (2D, polar) laser range-finder family in the corpus at any width. The other LiDAR families are:

- airborne DC LAS classification (u8), intensity (u16) and GPS time (f64);
- the GOOSE VLS-128 3D Cartesian xyz sweeps (f32).

These samples are scan-major polar range profiles: 1079 beams at 0.25° steps over ±134.75°, about 36.5 scans per second, from a person-carried platform indoors. It is the second LiDAR-type family at 32 bits in this collection effort.

## Source and rights

- Inventory and license: `cartographer_ros/docs/source/data.rst`, pinned to commit `ef0e971b50ed94b06fa29cdd12a311240c56c571` (30,746 bytes, SHA-256 `97187a77c1b906f9bcaf919455df5c61a6b71a0d7ada4a387a71d424a665a431`). It is identical to master on 2026-10-06.
- Objects: `https://storage.googleapis.com/cartographer-public-data/bags/backpack_2d/<bag>.bag`, an anonymous GCS bucket. The bucket listing is denied, so data.rst is the inventory: 56 bags, 47,163 s.
- Pins: each selected bag's size, base64 MD5, CRC32C, GCS generation, `index_pos`, chunk count and exact horizontal scan count are in `sources.tsv`. `download.sh` checks them before and after transfer.
- License: Apache-2.0. The "2D Cartographer Backpack – Deutsches Museum" section has its own rendered `License` subsection ("Copyright 2016 The Cartographer Authors / Licensed under the Apache License, Version 2.0"). It sits directly above the section's `Data` bag table and is separate from the RST file-header comment, so the grant covers the bag objects. `download.sh` re-validates this text and every pinned bag URL on each run.

## Shape and conversion

Each natural record is one recording session: one `.bag`, a continuous horizontal-laser stream with no separate upstream per-scan files. This is the same framing as the accepted EIT and ADCP recording recipes.

- **Decode.** A pure-stdlib ROS bag v2.0 parser reads the op-3 bag header, bz2 chunks (op 5), op-7 connection records and op-2 `horizontal_laser_2d` messages. The message type must be `sensor_msgs/MultiEchoLaserScan` with md5 `6fefb0c6...`.
- **Values.** The 4 bytes of `ranges[beam].echoes[0]` are copied unchanged, giving one row-major `scans × 1079` little-endian float32 matrix per bag in record-time order.
- **Excluded.** The IMU (float64), the vertical push-broom laser (different mounting and geometry), intensities, second and third echoes (3.3-3.9% of beams) and headers.
- **Missing values.** `60.0` (exactly `range_max`) is the driver's no-return code and is kept as-is, counted per sample. Zero-echo beams have no source range and become canonical NaN `0x7FC00000`, counted per sample: 157 values in 10 of 16 sessions.
- **Width.** Every finite value is `float32(n/1000)` for integer millimetres n. This is the published upstream float32 representation, not a local widening; it follows the `dandi_000020_patchseq_current_clamp_f32` ADC-lattice precedent.
- **Selection.**
  - Exclude the 3 bags flagged with horizontal-laser gaps.
  - Take the shortest eligible session per unit (b0, b1, b2) and per floor (OG, EG, UG).
  - Fill shortest-first while primary output stays at or below 950,000,000 bytes.
  - `b0-2014-07-21-12-49-19` is flagged only for a vertical-laser gap and is kept. Build and verify reject any horizontal gap above 1 s.

## Accepted output

- Population: 56 bags (b0 12, b1 5, b2 39; floors OG 43, EG 10, UG 3); 53 eligible.
- Primary samples: 16 (b0 ×7, b1 ×1, b2 ×8; OG 14, EG 1, UG 1), recorded 2014-07-11 to 2016-04-05.
- Scans: 209,373.
- Primary values: 225,913,467.
- Primary bytes: 903,653,868.
- Smallest sample: 5,522 scans (5,958,238 values, 23,832,952 bytes).
- Median sample: 12,426 scans (13,407,654 values).
- Largest sample: 26,053 scans (28,111,187 values, 112,444,748 bytes).
- Value range: 0.026 to 60.0 m, with 0 values off the mm lattice.
- `range_max` sentinel: 21,582,485 values (9.553%), 4.01-24.08% per session.
- Zero-echo NaN: 157 values (max 55 in one session).
- Maximum inter-scan gap: 0.068 s.
- Distinct values: 28k-43k per session.
- Download: 1,470,431,881 bytes of bags plus data.rst. About 60% of each bag is IMU and vertical-laser data that is not kept.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/cartographer_backpack2d_hokuyo_ranges_f32` passes with no warnings.
- **verify.sh:** I re-ran it; exit 0. It re-derived all 16 sessions through the index section with 0 mismatched scans, 0 off-lattice values, and matching hashes, counts and scope (`verify_totals samples=16 bytes=903653868 values=225913467`).
- **Recipe matches the download run:** all scripts and `sources.tsv` have mtimes before the driver's download run. The log shows 16/16 `bag_validation=ok`. `build.sh` reads only `.data/downloads`, and no script contains credentials.
- **Independent decode:** I wrote my own struct-based ROS bag decoder under `/tmp/autocollect/`. It reproduces two complete sessions byte-for-byte:
  - `b0-2014-07-11-10-58-16`: 5,522 scans, time_increment 1.7361e-05;
  - `b2-2016-01-19-14-10-47`: 11,230 scans, time_increment 1.7329e-05, 23 zero-echo beams.

  frame_id is `horizontal_laser_link`, the rate is 36.2-36.8 Hz, ranges are in metres and intensities (about 200-7000) are not emitted.
- **Byte statistics** (4 sessions across b0, b1, b2 and 2014/2015):
  - Non-sentinel q50 is 2.47-6.57 m and q99 is 15-31.5 m.
  - The low byte takes 125 distinct values, consistent with the mm lattice.
  - There are 0 identical consecutive scans, and the mean scan-to-scan change is 0.21-0.26 m.
  - No beam column is degenerate: none has a standard deviation below 5 cm and none is more than 90% sentinel.
- **Selection:** I re-derived it from the data.rst table. It is the 15 shortest eligible sessions plus the only b1 coverage session. The next-shortest session (513 s, about 81 MB) would exceed the budget, so 16 is the cap-limited maximum of whole sessions.
- **Rights:** I read the pinned data.rst and confirmed the data-section License subsection. I re-fetched master (same SHA-256) and sent a HEAD to the b1 bag (200, pinned size, MD5 and generation).
- **Novelty:** `novelty.py --url https://storage.googleapis.com/cartographer-public-data/bags/backpack_2d/ --terms cartographer hokuyo rosbag 'laser range' lidar MultiEchoLaserScan 'range finder' laserscan` matches only the candidate. The other LiDAR hits are DC LAS (8/16/64-bit) and GOOSE 3D xyz (32-bit).
- **Breadth:** the ledger has one other accepted LiDAR family at 32 bits (GOOSE).
