# UMich NCLT Velodyne HDL-32E revolution x,y,z uint16 development

## Outcome

Accepted `umich_nclt_velodyne_hdl32e_xyz_u16`. It keeps native uint16 LiDAR point coordinates from the University of Michigan North Campus Long-Term (NCLT) dataset, session 2013-01-10.

LiDAR xyz is already in the corpus at 32 bits (`goose_vls128_lidar_scan_xyz_f32`) and 64 bits (`orex_ola_l2_lidar_point_xyz_f64`). This family differs in three ways:
- it is a new upstream source;
- the publisher stores it natively as a 5 mm fixed-point offset-binary lattice;
- the coordinates are in a motion-compensated robot body frame, not the sensor frame.

The local 16-bit LiDAR family (`dc_lidar_2015_intensity_u16`) holds aerial return intensities, not coordinates. The novelty is therefore `new_source`, not a new modality. zlsim breadth verdict: OK. The nearest family is `mast_jwst_nircam_sw_uncal_ramps_u16`, at distance 0.0519 with compression loss 0.1447.

## Source and rights

- Source: the official NCLT S3 object `velodyne_data/2013-01-10_vel.tar.gz` in bucket `nclt.perl.engin.umich.edu` (us-east-2), linked from the NCLT download table.
- Compressed bytes: 2,926,183,916.
- S3 multipart ETag: `"3c9d1400e8ccec9c40bdd757221ad172-349"`, recomputed locally.
- SHA-256: `92118ba5dc8e197eb0dfd817a006b1acc20ff1efb2fa53be02f61d40d6438ccb`.
- Last-Modified: Tue, 27 Sep 2022 11:37:44 GMT.
- License: Open Database License 1.0 for the database and Database Contents License 1.0 for the contents.
  - The NCLT page states that the dataset may be used, shared and adapted, provided users credit the authors, offer publicly used adaptations under the same license, and keep redistribution open.
  - The README carries the IJRR 2016 citation (Carlevaris-Bianco, Ushani, Eustice) and the share-alike obligations.

## Shape and conversion

The archive is a gzip of a GNU tar. It decompresses to 4,609,914,880 bytes holding:
- `velodyne_hits.bin` (2,771,041,792 B, the raw sensor-frame packet stream, never used);
- then 5,120 `velodyne_sync/<utime>.bin` files in ascending time order (1,024.7 s at 0.2 s spacing).

Each sync file is the publisher's per-image revolution product (nclt.pdf §7.3):
- packed 8-byte records `<HHHBB` (x, y, z, intensity, laser_id);
- motion-compensated and expressed in the Segway body frame;
- metres = code × 0.005 − 100.

Conversion and selection:
- One sample is one sync file. Bytes 0–5 of every record are copied bit-exactly into an N×3 point-major little-endian uint16 array, in source hit order.
- Intensity and laser_id are dropped and nothing auxiliary is emitted.
- Selection is every 5th file in sorted utime order, i.e. one revolution per second.
- Files under 1,000 hits would be skipped; none was.
- The tarball is streamed and never extracted.

Source quirks, kept as published:
- 10 selected samples are the publisher's ~3-revolution files (33 of 5,120 overall).
- 24 selected samples show no azimuth wrap.
- Hit counts vary with the scene, because no-return shots are omitted upstream.

## Accepted output

- Sync files in archive: 5,120 (229,371,006 hits; maximum code 37,848)
- Selected: 1,024 (stride 5); skipped below 1,000 hits: 0
- Primary samples: 1,024
- Hits: 46,219,538
- Primary values: 138,658,614
- Primary bytes: 277,317,228
- Minimum sample: 41,607 values
- Median sample: 135,510 values
- Maximum sample: 536,853 values
- Hits per sample: min 13,869, p50 45,171, p99 82,717, max 178,951
- Codes:
  - overall: 1,959 to 37,120
  - x: 1,959 to 37,028 (−90.2 to +85.1 m)
  - y: 2,987 to 37,120 (−85.1 to +85.6 m)
  - z: 11,356 to 22,559 (−43.2 to +12.8 m, z down)
- Aggregate sample SHA-256 (index order): `735534d4e23b915f0431feb531cc07e1d5b1e864bfd1dc4da673cea9ebd5578a`

## Judge checks

- **Gate:** `gate.py` PASS, no warnings.
- **verify.sh:** I re-ran it; it passed in 39.7 s with the pinned archive SHA-256 and the aggregate hash above.
- **Build is local:** build.sh reads only the local tarball, members.tsv and receipt. Neither build nor verify does network I/O.
- **Download provenance:** download.sh (mtime 03:54:43) predates the only download run (03:55:23).
- **Independent byte check:** I streamed the archive with my own script and re-extracted samples 0, 129, 500, 777 and 1023. All match bytes 0–5 of every source record exactly.
- **Dominant value explained:** every sample's most common value is z code 19794 (−1.03 m), at 0.9–2.5% of values. The source laser_id field shows these hits are all from laser 15, the HDL-32E's 0° beam:
  - its z is a single value while x/y spread over tens of metres;
  - neighbouring codes 19790–19798 are empty;
  - it is real horizontal-beam geometry at sensor height, not fill or out-of-range points;
  - no hit lies within 1 m of the body origin.
  - The README does not mention this, but it is not a defect.
- **Near-duplicates:** the first ~12 samples come from a stationary start.
  - Consecutive samples there share 0.15–0.6% exact triplets and ≤0.31 of 10 cm voxels.
  - Later pairs share 0.03–0.11 of 10 cm voxels.
  - No byte-level near-duplicates were found.
  - Within-sample triplets are essentially unique.
- **License:** I fetched the NCLT page myself and confirmed the ODbL/DbCL text and the direct link to this exact tarball. No credentials appear in any script.
- **Novelty:** `novelty.py` with the URL, the terms, `--vocabulary`, `--type laser_range` and `--list-width 16` shows no NCLT material locally, in the registry or downstream, and no 16-bit LiDAR coordinate family. GOOSE (f32) and OREX OLA (f64) are other sources of the same modality.
