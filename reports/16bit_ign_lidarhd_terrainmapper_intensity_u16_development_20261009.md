# IGN LiDAR HD TerrainMapper intensity uint16 development

## Outcome

Accepted `ign_lidarhd_terrainmapper_intensity_u16`. Each sample is the native LAS 1.4 point-format-6 `Intensity` field (unsigned 16-bit, record offset 12) of every point in one complete 1 km × 1 km classified COPC tile. All 12 tiles come from one acquisition block of the French national IGN LiDAR HD programme:
- mission `21LHD2GO`, a 50 km × 50 km block in south-west France;
- flown on 2023-08-09 and 2023-08-17 by a single Leica TerrainMapper, serial 90560;
- classified with `IGN_AUTO_V5`;
- delivered once, as `NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22`.

The novelty is new content in a known modality (airborne lidar intensity at 16 bits), not a new modality. Two 16-bit LAS intensity families are already in the local corpus:
- `dc_lidar_2015_intensity_u16` uses only 0..255 (about 95 distinct values). Its feature distance from this family is 0.41.
- `noaa_ngs_potomac_topobathy_vq880g_intensity_u16` is RIEGL VQ-880-G topobathy intensity, stretched to 0..65535 on a lattice of about 25. Its feature distance is 0.153.

This family is a raw step-1 TerrainMapper stream: roughly 300..4400, with 4,331–5,962 distinct values per tile.

## Source and rights

- **Delivery:** IGN Géoplateforme download service, `https://data.geopf.fr/telechargement/download/LiDARHD-NUALID/NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22/`. Its Atom feed has 2,501 entries (2,500 COPC tiles plus `index.vpc`) and publishes each file's byte length and MD5.
- **Metadata:** WFS layer `IGNF_LIDAR-HD_METADONNEE:metadata`, filtered to `code_mission='21LHD2GO'`. All 2,500 records carry `capteur = ["Leica TerrainMapper:90560"]`, `procede_classement = IGN_AUTO_V5` and edition 2025-09-22.
- **Pinning:** `sources.tsv` pins 12 tiles with URL, size, Atom MD5, LAS header point count and SHA-256 (from the first download). Pinned download total: 2,071,849,594 bytes.
- **License:** Licence Ouverte / Open Licence 2.0 (Etalab). The data.gouv.fr API record `nuages-de-points-lidar-hd` (organization: Institut national de l'information géographique et forestière) carries license id `lov2` with flags `okd_compliant` and `domain_data`. Its resources include the WFS metadata layer that resolves the pinned tile URLs. The IGN geoservices CGU page names Licence Ouverte / Etalab as the default licence. Etalab 2.0 allows reuse, redistribution and commercial use with attribution.
- **Access and safety:** anonymous HTTPS with no credentials. The data contains no personal data.

## Shape and conversion

The tiles are COPC 1.0 files: LAS 1.4, PDRF 6, 30-byte records, compressed with LASzip compressor 3 (POINT14 v3 only). They are decoded with the unmodified repository decoder `tools/laz/laszip.py`.

Bytes 12–13 of every record are copied unchanged, one little-endian uint16 `.bin` per tile. Nothing is filtered: all classes and all returns are kept. Point order is the file's stored COPC octree-node order, not acquisition order.

**Selection (deterministic, `scripts/select_tiles.py`):**
- 12 anchors on an interior 4 × 3 grid (NW-corner km x 442/454/466/478, y 6342/6358/6374), each at least 6 km from every block edge;
- each anchor takes the nearest tile with 15M–32M catalogue points and at most 230 MB;
- 11 anchors took their own tile, and anchor 442/6374 moved to 0441-6373.

**Download checks (`download.sh`):** size, MD5, SHA-256, LAS/COPC structure (COPC info VLR, Lambert-93 WKT VLR, COPC hierarchy EVLR) and the header point count.

**Build checks (`build.sh`):**
- decoded point count, points-by-return against the header, and decoded XYZ inside the header bounds;
- regime guards: at least 1,000 distinct values, a max of at least 1,000, and no single value above 5% of a tile.

**Missing values:** there is no sentinel.
- 360 zeros, all in tile 0442-6342. These are IGN class-66 virtual points.
- 54 saturated values (65535) across 6 tiles.

Both are kept as recorded.

## Accepted output

- Primary samples: 12
- Primary values: 312,419,900
- Primary bytes: 624,839,800
- Minimum sample: 22,769,214 values
- Median sample: 25,792,357.5 values
- Maximum sample: 29,005,724 values
- Distinct values per tile: 4,331–5,962
- Order-0 entropy per tile: 11.06–11.69 bits
- Percentiles per tile: p0.1 288–335, p50 912–1789, p99.9 3261–4388
- Largest single-value share per tile: at most 0.12%
- Zero fraction: 1.15e-6. Saturated (65535) fraction: 1.73e-7.
- Aggregate SHA-256 of the samples, concatenated in sample_path order: `c1c77431f82dd1ee6b6bd93375a68b539c85d0ca19dd1d595bd2d91d3b289e66`

## Judge checks

- **Gate:** `gate.py` passed with no warnings.
- **verify.sh:** I ran it myself, from 00:17 to 00:24, exit 0. All 12 tiles were re-decoded and byte-compared through a separate `struct.iter_unpack` extraction. Index fields, manifest totals, floors and the cap were checked.
- **Download log:** the driver's latest `download.log` shows 12 cache hits, each passing the size/MD5, LAS/COPC structure and pinned SHA-256 checks.
- **Independent decode:** I decoded 600k-point prefixes of tiles 0442_6358, 0466_6374 and 0442_6342 with my own `<iiiHBBBBhHd` layout. Intensity matched the stored samples exactly. Adjusted GPS times (3.7562e8–3.7634e8) fall on 2023-08-09 and 2023-08-17, and return numbers are valid.
- **Physical plausibility:** median intensity by return type is 1841–2484 for single returns, 862–1243 for first-of-many and 758–789 for last-of-many. By class it is 1631–2514 for ground and 873–1105 for high vegetation. This is consistent with NIR lidar over the forest and agricultural land of south-west France. The class-66 virtual points decode with intensity 0 and point source id 0.
- **Byte statistics (four tiles):**
  - every integer between p1 and p99 occurs (lattice occupancy 1.000);
  - even share 0.500;
  - low-byte entropy about 8.0 bits, high-byte entropy 3.3–3.8 bits, so the width is not hollow or widened;
  - delta entropy 11.2–11.5 bits, lag-1 r 0.43–0.77;
  - equal neighbours 0.08–0.13%;
  - zero duplicated 8 KB blocks.
- **Homogeneity:** the three flight groups (point source ids 9–11, 24–26, 40–41) differ in median by up to about 50%, but share one unit, one step-1 lattice and overlapping value bands. This is within-process variation, not a different regime. No other sensor appears in the block.
- **Rights:** I fetched the data.gouv.fr API record (license `lov2`, organization IGN) and the IGN CGU page (Etalab as default). No credential patterns appear in any script.
- **Novelty:** `novelty.py` (URL, terms, vocabulary, type/instrument/archive) found no prior use of `data.geopf.fr` or LiDAR HD. The builder's novelty note named only dc_lidar. I also checked `noaa_ngs_potomac_topobathy_vq880g_intensity_u16`, accepted earlier the same day and present in the zlsim library. Its percentile feature distance is 0.1533, outside the gate's 10-neighbour set. Driver-measured breadth is OK: nearest `sarscov2_tem_projection_i16` at 0.0637 with loss 3.16%. There were no fill warnings.
- **Volume:** 12 samples is below the soft target of about 20. At about 52 MB per natural tile, 19 tiles would reach the 1 GB cap. 625 MB is already well above the downstream per-family draw, and `swisstopo_swisssurface3d_alps_las_z_i32` (15 tiles) is accepted precedent, so this is accepted rather than sent back for repair.
- **Process note:** in an earlier round the builder re-fetched about 2 GB into `/tmp` while testing, because `stat` measured symlinks. The recipe now uses `stat -L`, and the driver's re-run exercised it. No recipe defect remains.
