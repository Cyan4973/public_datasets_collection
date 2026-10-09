# swisstopo swissSURFACE3D 2021 high-alpine lidar LAS Z int32 development

## Outcome

Accepted `swisstopo_swisssurface3d_alps_las_z_i32`. It collects the native LAS int32 Z record code of every lidar return in 15 complete 1 km² tiles of swisstopo's swissSURFACE3D classified airborne point cloud (2021 acquisition, Bernese Oberland / Aletsch high Alps). The output is one sample per tile, in producer file order.

This is the first swisstopo source in the corpus and the first airborne-lidar per-return elevation code at any width. The nearby families differ:
- The existing airborne LAS families take other fields: DC LiDAR intensity u16, classification u8 and GPS time f64; Scotland Phase I scan angle i8; Coastal Maine topobathy classification u8.
- The laser-ranging coordinate families are vehicle float32 xyz (GOOSE), asteroid float64 xyz (OSIRIS-REx OLA) and lunar orbital radius/range in int32 mm (LOLA).
- The elevation rasters are gridded integer metres (SRTM HGT i16, MOLA i16, downstream geonames_dem_i32).

Novelty kind: new source. Breadth (zlsim, 32-bit): **OK**.

## Source and rights

- **Source:** data.geo.admin.ch STAC 0.9 collection `ch.swisstopo.swisssurface3d`, anonymous HTTPS asset hrefs `<item>/<item>_2056_5728.las.zip`.
- **Pins:** 15 zips, 2,761,286,143 bytes. For each zip, `sources.tsv` pins:
  - zip size and SHA-256 (from the STAC `checksum:multihash`, 0x1220 sha2-256);
  - member name, member size (= 227 + 28·n) and CRC-32;
  - point count and header Z bounds.
- **License:** swisstopo Open Government Data, "Opendata BY".
  - The geocat.ch ISO record `5cb73a88-887c-432d-b3a4-f4ea2b508a51` for "swissSURFACE3D, die klassifizierte Punktwolke der Schweiz" carries the legal constraint "Opendata BY: Open use. Must provide the source."
  - The swisstopo terms page says: "The free geodata and geoservices of swisstopo may be used, distributed and made accessible. Furthermore, they may be enriched and processed and also used commercially. A reference to the source is mandatory."
  - The manifest cites "©swisstopo".
  - The STAC `license: proprietary` field is the generic non-SPDX placeholder.
- **Safety:** no credentials. The data is uninhabited high-alpine terrain and only Z is emitted, so it contains no personal data.

## Shape and conversion

- **Selection** (`scripts/discover.py`, re-derived by the judge from the live listing):
  1. The STAC bbox `7.85,46.40,8.15,46.60` returns 647 items (2021: 398, 2022: 224, 2023: 25).
  2. Keep 2021 tiles with no item from another year: 327. This drops partial acquisition-block border tiles.
  3. Keep the uniform delivery profile (LAStools `las2las` LAS 1.2, PDRF 1, 28-byte records, no VLRs, scale 0.01, Z offset 0): 325. This drops the two `lasmerge` tiles 2640-1153 and 2640-1154.
  4. Sort by id and keep index `floor(j·325/15 + 325/30)` for j = 0..14.
- **Natural record:** one 1 km² tile, a single deflated `<E>_<N>.las` member of 357–616 MB. One sample is the complete Z field of the tile.
- **Conversion:** stream the member through `zipfile` without extracting it, with the CRC-32 enforced at EOF. Copy bytes 8–11 of every 28-byte record, the little-endian int32 Z, unchanged.
  - Height = Z × 0.01 m above LN02, offset 0.
  - All returns and all classes are kept; no records are dropped and no values are imputed.
- **Fatal checks in build:** data min/max must equal the header bounds; codes must lie in 100,000–500,000; at least 10,000 distinct values; top value at most 5% of a tile.
- **Natural behaviour kept as published:** point order follows the producer's file layout (spatially coherent, not GPS-time monotonic), and per-tile density varies with terrain and flight-line overlap.

## Accepted output

| | |
|---|---|
| tiles (samples) | 15, LV95 E2632–2653 km / N1138–1154 km |
| points per tile | 12,768,345 .. 21,983,757; median 15,627,117 |
| primary values | 238,892,601 |
| primary bytes | 955,570,404 |
| pinned download | 2,761,286,143 bytes (15 zips) |
| Z codes | 161,267 .. 388,304 (1,612.67–3,883.04 m) |
| distinct values per tile | 33,694 .. 85,250 |
| top-value share per tile | 0.0025% .. 0.0227% |
| median \|ΔZ\| per tile | 3 .. 94 (0.03–0.94 m) |
| order-0 delta entropy per tile | 5.43 .. 10.02 bits |
| concatenated samples SHA-256 (sources order) | `c4def17fabf227c340be7c0879ff956d8e380169a41e5d10ab9a137e6c0245ef` |

Breadth (zlsim): verdict OK. The nearest family is `fingrid_nordic_grid_frequency_10hz_f32`, at distance 0.0593 with loss 0.0207 and mode_share 0.0005.

Limitations:
- The sample count (15) is bounded by whole ~64 MB tiles under the 1 GB cap, not by the source, which offers 325 eligible tiles in this bbox alone.
- The values use about 19 of 32 bits: byte 3 is constant 0. This is the native LAS width.

## Judge checks

- **Gate.** `gate.py`: PASS, no warnings (15 samples, 238,892,601 values, 955,570,404 bytes, median 15,627,117).
- **verify.sh (re-run myself).** Exit 0, `verify=ok samples=15 bytes=955570404`. Every tile is re-derived by whole-record `struct.iter_unpack` and compared byte for byte, and the SHA-256, index fields, header Z bounds and manifest totals are checked. build.sh reads only local zips. download.sh is curl-only, resumable and pinned, and rejects bad profiles, sizes and CRCs.
- **Independent decode.** My own full PDRF-1 record decode of 2645_1154 gave 0 Z mismatches over 16,909,252 records.
  - X/Y are 0–99,999 (tile-relative cm) and the offsets are the tile corner.
  - Classes: 1 (1.16 M), 2 (15.75 M), 3 (37).
  - 6 point-source IDs.
  - Points by return: 16.87 M / 33 k / 3.3 k.
  - The GPS time (adjusted standard, about 3.178e8 s) dates the flight to about October 2021.
- **Byte statistics on all 15 samples.**
  - Data min/max equal the header bounds.
  - byte2 takes values 2–5 and byte3 is 0, so values exceed uint16 and the width is native, not widened.
  - No duplicated 4096-value blocks, and all SHA-256 values are distinct.
  - Zero-delta share is 0.4–9.1%: the highest is 2650_1153, a smooth glacier surface. The largest deltas are in 2652_1142, a steep forested slope where 4.7% of |Δ| exceed 10 m.
  - No fill or dominant value.
- **Selection.** The live STAC listing reproduces 647 → 327 → 325 → the 15 pinned ids exactly. A range-probe of the two excluded tiles confirmed `lasmerge (version 231204)` headers. All 15 pinned SHA-256 values and hrefs equal the STAC multihash and asset hrefs.
- **Rights.** I opened the geocat ISO XML for this exact product (MD_LegalConstraints "Opendata BY") and the swisstopo terms page (use, distribution, processing and commercial use allowed; source reference mandatory). A grep for credentials found nothing.
- **Novelty.**
  - `novelty.py --url` (data.geo.admin.ch, ch.swisstopo.swisssurface3d) and `--terms` (swisstopo, swisssurface3d, LN02, LV95, lidar, las_z, laszip, elevation, lola): no swisstopo source or LAS Z series in datasets, the registry, the ledger or downstream.
  - `--type laser_range --instrument swisstopo_swisssurface3d_airborne_lidar --archive "data.geo.admin.ch (swisstopo STAC)"`: 12 same-type families, 0 same instrument line, 0 same archive.
- **Volume.** The cap-bounded count of whole natural records matches the accepted COMET LiCSAR (4 frames) and EMPIAR-10318 (24 frames) precedents. The kept-to-download ratio of 35% leaves a large absolute signal.
