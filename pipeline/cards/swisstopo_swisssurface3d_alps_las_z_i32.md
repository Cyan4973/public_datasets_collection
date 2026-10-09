# swisstopo swissSURFACE3D (2021 Bernese Oberland High-Alpine Tiles) Classified Lidar Point Cloud LAS Scaled Int32 Z Record Coordinates

- Candidate id: `swisstopo_swisssurface3d_alps_las_z_i32`
- Width: int32
- Quantity: LAS point-record Z field: native little-endian int32 elevation code (scale 0.01 m, offset 0, LN02 heights) of each return; high-alpine terrain about 1,500-4,100 m, so stored values are about 150,000-410,000
- Source: https://data.geo.admin.ch/browser/index.html#/collections/ch.swisstopo.swisssurface3d
- Resources: https://data.geo.admin.ch/api/stac/v0.9/collections/ch.swisstopo.swisssurface3d/items?bbox=7.85,46.40,8.15,46.60&limit=100, https://data.geo.admin.ch/ch.swisstopo.swisssurface3d/swisssurface3d_2021_2637-1149/swisssurface3d_2021_2637-1149_2056_5728.las.zip
- License: swisstopo Open Government Data terms (free use, including commercial, with mandatory source attribution)
- License evidence: https://www.swisstopo.admin.ch/en/terms-of-use-free-geodata-and-geoservices
- License quote: The free geodata and geoservices of swisstopo may be used, distributed and made accessible. Furthermore, they may be enriched and processed and also used commercially. A reference to the source is mandatory.
- Natural record: One 1 km2 swissSURFACE3D tile (one <x>_<y>.las inside its .las.zip) = one sample: the full Z column of the tile in file order
- Estimated samples: 6
- Estimated primary values: 85,000,000
- Estimated download bytes: 1,000,000,000
- Estimated primary bytes: 340,000,000
- Decode path: Query the STAC items API for the bbox, keep only the 2021 acquisition items, and pick ~6 tiles whose zip is 140-170 MB (about 12-15M points each). curl them. In Python, zipfile streams the single deflated .las member (no LAZ decoding needed). Parse the LAS 1.2 header (pf1, 28-byte records), then take Z as the int32 at record offset 8 with struct.iter_unpack('<8xi16x'). Emit little-endian int32.
- Novelty kind: new_source
- Measurement type: laser_range
- Instrument line: swisstopo_swisssurface3d_airborne_lidar
- Archive collection: data.geo.admin.ch (swisstopo STAC)
- Novelty evidence: novelty.py --url data.geo.admin.ch/ch.swisstopo.swisssurface3d with terms swisssurface3d/swisstopo: no matches anywhere. The corpus has no swisstopo source and no lidar point elevation codes. The existing elevation families (geonames DEM i32, SRTM HGT i16, MOLA i16) are gridded integer metres, not per-return cm codes in point order.
- Homogeneity: One national programme (swissSURFACE3D), one acquisition year (2021), one contiguous high-alpine area (Bernese Oberland around 2631-2637/1138-1149 km LV95), and one delivery format (LAStools las2las LAS 1.2 pf1, scale 0.01, Z offset 0). Only the Z field. Do not mix in other years or lowland tiles.
- Risks: Tiles are large (12-22M points; zips 140-260 MB, LAS about 490 MB uncompressed), so only ~6-8 fit the ~1 GB primary cap and a sensible download. The sample count is near the soft minimum, set by the natural 1 km2 boundary. Z uses about 19 bits (upper byte constant 0); it is still well beyond u16, so int32 is the native width. X/Y in this programme are offset to the tile corner (stored 0-99,999, about 17 bits), so only Z suits 32 bits. The zip CRC check should be enforced. The byte gate might still compare Z to other elevation-like streams.
- Probe evidence: HEAD on 25 alpine tile zips gave content-length 139-258 MB. A range GET of the first 64 KB of swisssurface3d_2021_2637-1149 zip, inflated: member '2637_1149.las' (method 8, csize 200,429,243, usize 492,699,427); LAS 1.2, pf1, rl 28, n=17,596,400, scale 0.01, offset (2,637,000; 1,149,000; 0), Z 3,010.27-3,894.03 m, so stored Z is 301,027-389,403. The STAC bbox query returned 100 items.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_211441.jsonl`).
