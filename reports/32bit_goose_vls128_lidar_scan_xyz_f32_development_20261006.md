# GOOSE VLS-128 LiDAR sweep xyz float32 development

## Outcome

Accepted `goose_vls128_lidar_scan_xyz_f32`: per-point Cartesian x, y, z coordinates of published roof-LiDAR sweeps from the GOOSE 3D validation split.

This is the first spinning-LiDAR point-cloud family in the corpus at any width. The local and downstream LiDAR families so far are airborne DC LAS classification (u8), intensity (u16) and GPS time (f64), none of which carry coordinates. The 32-bit point-like families (ModelNet10 CAD vertices, wwPDB atom coordinates, building footprints) are different material. These samples are firing-order, ring-structured range returns from a ground vehicle.

## Source and rights

- Source: official GOOSE archive `https://goose-dataset.de/storage/goose_3d_val.zip`
- Archive bytes: 3,498,402,435; Last-Modified 2025-03-19; ETag `"67da9ea9-d0856283"`
- CHANGELOG member: "2024-07-26: Initial upload of GOOSE 3D with 9892 annotated LiDAR scenes."
- Fetched: one 316,905-byte tail (sha256 `9c4e49e30f5a9b98ec92d5799850dc2c938908b19eb5e202a18f00e7f6e29a4e`), which holds the LICENSE, CHANGELOG and label-mapping members, the 1,925-entry central directory, the ZIP64 end records and the EOCD; plus 64 exact member byte ranges (184,014,848 bytes)
- License: CC BY-SA 4.0

The download page says "The GOOSE Datset is published under the CC BY-SA 4.0 License." The GitHub README says "The data is published under the CC BY-SA 4.0 License" (the code is MIT). The archive's own `LICENSE` member is the full Attribution-ShareAlike 4.0 International legal code (20,138 bytes, sha256 `28a9529c7d0bb4dc51f4bf5c116a3d16ef247a052f7591466768ddf563fd1cf5`). `download.sh` pins its CRC and wording. Attribution (Mortimer et al., ICRA 2024, arXiv:2310.16788), a modification notice and the share-alike obligation are recorded in the README and manifest. CC BY-SA precedent: `exomol_state_energy_levels_f64`, `zenodo_crab_giant_pulse_sigmf_ci16`, `asterisk_core_sounds_ulaw_u8`.

## Shape and conversion

Each natural record is one published sweep file, `lidar/val/<seq>/<seq>__<frame>_<ts>_vls128.bin`. It is a stored (method 0) SemanticKITTI-layout array of N × 4 little-endian float32 fields: x, y, z, remission.

- Each sample keeps fields 0..2 of every point bit-exactly, in source order, as an N × 3 point-major float32 array.
- Remission is integer-valued 0..255 in every sweep, so it is dropped rather than emitted as a widened integer. Labels are not used.
- ZIP decoding parses local headers and resolves ZIP64 extended-information offsets (1,214 central-directory records). Each payload is checked against the central-directory CRC32.
- Selection: for each of the 8 val sequences, sort sweeps by frame and take indices `floor((2k+1) n / 16)` for k = 0..7. `download.sh` re-derives this from the live central directory.
- Missing-value policy, shared by build and verify: any NaN, infinity or all-zero point is fatal. The build found 0 of each.

Disclosed source quirks, kept as published:

- 7 partial-azimuth files: 6 in `2023-05-17_neubiberg_sunny` covering 156 to 324°, and 1 in `2023-03-03_garching_2` covering 323°.
- 15 sweeps contain 674 to 2,816 counter-rotation order jumps, at most 3.2% of points.
- 18 sweeps contain likely multipath ghost points down to z = -70.9 m.

The word "complete" in the manifest description refers to whole published files, not full 360° revolutions. The manifest's filtering field states the partial files explicitly.

## Accepted output

- Sequences: 8 (2022-07-22_flight, 2022-08-30_siegertsbrunn_feldwege, 2022-09-21_garching_uebungsplatz_2, 2022-12-07_aying_hills, 2023-01-20_aying_mangfall_2, 2023-03-03_garching_2, 2023-05-15_neubiberg_rain, 2023-05-17_neubiberg_sunny)
- Primary samples: 64 (8 per sequence, out of 961 val sweeps)
- Points: 11,500,411
- Primary values: 34,501,233
- Primary bytes: 138,004,932
- Smallest sample: 75,290 points (225,870 values)
- Median sample: 583,156.5 values
- Largest sample: 217,338 points (652,014 values)
- Download on disk: 184,354,632 bytes
- Aggregate sample SHA-256 (index order): `a7cace02b1c8d5f2433d66d043ef1340eeaf5728d1aad63f396342597ddea5d6`
- Aggregate payload SHA-256 (sources.tsv order): `303d8a9e19ecb1221469bec0b971c41c67805f93c467869ca46182e37caa45b0`

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/goose_vls128_lidar_scan_xyz_f32` passes with no warnings.
- **verify.sh:** I re-ran it; it reports verify_ok with 64 samples and 138,004,932 bytes.
- **Recipe matches the download run:** download.sh, goose_zip.py and sources.tsv mtimes predate the driver's download run. The download log shows tail validation ok and 64/64 members fetched and CRC-checked.
- **build.sh is local-only:** it reads only `.data/downloads`. No credentials appear in any script.
- **Independent re-derivation:** my own struct re-derivation of 8 samples (one per sequence) equals source fields 0..2. Both aggregate SHA-256 values reproduce.
- **Byte statistics:**
  - Coordinates span about ±200 m; range runs 1.0 to 200 m.
  - Trailing-zero counts in the mantissa follow a natural geometric distribution, with no mm or other lattice.
  - Distinct-value fractions are about 0.999 for x and 0.81 to 0.87 for z.
  - Elevation angles span -25° to +15° in 125 to 128 dense rings in all 8 sequences, which is VLS-128 Alpha Prime geometry in an unrotated sensor frame.
  - The lowest ring's median z is -1.74 to -2.23 m in every sequence, a consistent sensor height.
- **Remission:** integral (max 101 to 252) in every sweep, so dropping it loses no float content.
- **Duplicates:** all 64 samples have distinct SHA-256s, and no sweep shares exact xyz triples with another sweep of its sequence.
- **Rights:** I fetched the GOOSE setup page and the GitHub README myself; both state CC BY-SA 4.0 for the data. I read the archived LICENSE member; it is the full BY-SA 4.0 legal code, with no NC or ND terms.
- **Novelty:** `novelty.py --url https://goose-dataset.de/storage/goose_3d_val.zip --terms goose lidar vls128 velodyne 'point cloud' semantickitti kitti pointcloud ouster` matches only the candidate itself. The other LiDAR hits are DC LAS at 8, 16 and 64 bits.
- **Breadth:** the pipeline ledger has no other accepted LiDAR family at 32 bits.
