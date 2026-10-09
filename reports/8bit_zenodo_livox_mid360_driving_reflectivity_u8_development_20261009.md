# Livox MID-360 driving per-point reflectivity uint8: development report

## Outcome

Accepted `zenodo_livox_mid360_driving_reflectivity_u8`. Each sample is one complete `/livox/lidar` frame (`sensor_msgs/msg/PointCloud2`, about 10 Hz) from a Livox MID-360 solid-state lidar. The MID-360 scans a non-repetitive rosette pattern. The source is K. Koide's (AIST) "Driving SLAM Test with Livox MID360" rosbag2 recording. Each sample holds the per-point calibrated reflectivity at the sensor's native 8-bit width, in native scan order, with no-return slots kept in place as 0.

- **Novelty:** new content in a known modality. The corpus already holds 8-bit driving-lidar calibrated reflectivity from `boreas_velodyne_alpha_prime_intensity_u8`, a spinning 128-beam Velodyne that keeps returned points only. This recipe adds a different instrument line: a Livox solid-state rosette scan with 4-line firing groups and a fixed-cadence frame that includes no-return slots. It is the first recipe from this Zenodo record. No livox or mid360 term matches anywhere in the corpus, registry, ledger or downstream.
- **Breadth (zlsim):** OK. The nearest family is `sevir_vil_storm_event_cube_u8`, at distance 0.0675 with loss 0.0074. Boreas is not among the 10 nearest neighbours. Own compression ratio is 2.29.

## Source and rights

- **Source:** Zenodo record 14841855 (DOI 10.5281/zenodo.14841855), published 2025-02-10. It holds a single file, `rosbag2_2024_04_16-14_17_01.zip`: 517,088,133 bytes, Zenodo MD5 `0836c50859bb1af591966b69da166186`.
- **License:** CC BY 4.0. The record API reports `"license": {"id": "cc-by-4.0"}` and open access, with no added restrictions. `download.sh` re-checks the license id, size and MD5 against the live record JSON before accepting the payload.
- **Attribution:** Koide, Kenji (AIST), *Driving SLAM Test with Livox MID360*, Zenodo, doi:10.5281/zenodo.14841855.
- **Zip contents:** two deflated members, `metadata.yaml` and one rosbag2 SQLite db3 of 1,468,932,096 bytes.
  - Storage is sqlite3 with no bag compression.
  - The db3 holds 2,772 `/livox/lidar` PointCloud2 messages, 55,435 `/livox/imu` messages and 10 `/rosout` messages.

## Shape and conversion

- **Natural record:** one `/livox/lidar` message. Points per frame are 19,776–20,256, always a multiple of 96 (the driver's packet size). The median is 19,968.
- **Decode:**
  1. The db3 is extracted with `zipfile` (CRC-checked) to a temporary path. It is deleted after build and after verify.
  2. Messages are read with stdlib `sqlite3`: `messages JOIN topics WHERE name='/livox/lidar' ORDER BY timestamp, id`.
  3. Each message is parsed as CDR-LE PointCloud2 with 4-byte alignment, honouring the fields array: x, y, z, intensity as float32 at 0/4/8/12; tag u8 at 16; line u8 at 17; timestamp f64 at 18; point_step 26.
- **Conversion:** the float32 `intensity` of every point is written as one uint8, in point order. Build and verify accept only the 256 float32 bit patterns of the integers 0..255; NaN, −0.0, fractions and out-of-range values are fatal. The cast is therefore lossless and restores the sensor's native one-byte reflectivity. Nothing is clamped, rescaled or filtered.
- **No-return slots:** these are slots where the driver emits x=y=z=0 with reflectivity 0. They are kept in place because they are part of the native fixed-cadence frame and their positions follow the scene geometry. This matches the accepted DIODE and Cartographer precedents, which preserve native no-return codes.
- **Not emitted:** geometry, the per-point timestamp, tag, line, IMU and the other topics.

## Accepted output

- **Primary samples:** 2,772, every lidar message in the record.
- **Primary values and bytes:** 55,440,864.
- **Sample size:** minimum 19,776, median 19,968, maximum 20,256 values.
  - Frame counts by size: 19,776 ×10, 19,872 ×203, 19,968 ×1,492, 20,064 ×980, 20,160 ×85, 20,256 ×2.
- **Values:**
  - All 256 values are present.
  - Distinct values per frame: minimum 95, median 134, maximum 188.
  - The median non-zero value is 19, and values ≤ 10 cumulatively make up 66.2% of all values.
  - Retro-reflective values (151–255) are 0.138% of all values; 2,649 frames exceed 150 and 1,134 frames reach 255.
- **Zeros:** 48.8% of all bytes.
  - Per-frame zero fraction: minimum 18.6%, median 47.8%, maximum 77.0%.
  - No-return slots are 47.9% of all slots: minimum 18.1%, median 47.1%, maximum 75.6% per frame.
  - The most common value in every frame is 0, with a maximum share of 77.0%. Build and verify both reject any frame above 80%.
- **Aggregate SHA-256** of the samples concatenated in index order: `48af404187d46a84d89274591bf485643ee56450dd68ca6180bfd45b5f0d494d`.

## Judge checks

- **Gate:** `gate.py` passed with no warnings.
- **Verify:** the judge re-ran `verify.sh` and it passed in 21 s. Verify works independently of the build helpers:
  - it re-checks the zip MD5 and re-extracts the db3;
  - it parses the CDR with its own offset arithmetic and decodes every point with `struct.iter_unpack('<3ffBBd')`;
  - it compares all 2,772 samples byte-for-byte, then checks the index sha256 and min/max, the inventory and the manifest totals.
- **Local-only build:** `build.sh` and its scripts contain no network calls and read only `.data/downloads/<id>/`. `download.sh` uses curl only, with resume (`-C -`), a stall-based speed limit and a one-byte liveness range GET.
- **Source cross-check:** the judge re-decoded 11 frames spread across the drive from a temporary db3 extract under `/tmp`, which was deleted afterwards.
  - Slots with xyz=0: 103,872 carry reflectivity 0, and 1 carries a non-zero value. Returned points with reflectivity 0: 2,036.
  - `line` equals i mod 4 in every slot. The time step per 4-line group is ~19.7 µs, consistent with a 200 kHz sensor.
  - Returned points at reflectivity 0–24 have a median range of 13.3 m.
  - Only `tag` 0 appears on no-return slots.
- **Zero structure:** about 69% of zero bytes sit in runs of 64 or more (sky and open space above the horizon); the rest are scattered single or short slots. The per-frame zero fraction tracks the scene along the drive. The driver's fill warning list is empty.
- **Near-duplicates:** all 2,772 sample hashes are unique. None of the 565,840 aligned 64-byte chunks with at least 8 distinct values is repeated. Consecutive frames share only 0.4–2.9% of non-zero positions.
- **Rights:** the judge read the downloaded record JSON and re-fetched the record API live. Both show cc-by-4.0, open access and the single pinned file. The scripts contain no credentials, and no personal data is emitted.
- **Novelty:**
  - `novelty.py --url` on the zip URL with livox, mid360, mid-360, koide and rosbag2 matches only this staging recipe and its own ledger row.
  - `--terms lidar reflectivity intensity` shows that Boreas is the only 8-bit lidar-intensity family; the other lidar intensity families are 16-bit airborne LAS.
  - `--vocabulary` and the breadth-key query find 0 same-instrument families and 6 unrelated same-archive families.
- **Volume:** the recipe takes the full population of the record. 55.4 MB is comparable to Boreas. The ~1/9 extraction ratio from the 517 MB download is unavoidable, because reflectivity is interleaved in 26-byte point records and IMU traffic. Each frame is a materially sized natural record.
