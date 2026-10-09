# USGS 3DEP TX Lubbock 2011 Lidar Point Cloud (LAS 1.2 PDRF 1, LAZ): Native Per-Point GPS Week Time Float64

- Candidate id: `usgs_3dep_lubbock2011_las_gps_week_time_f64`
- Width: float64
- Quantity: Per-point GPS time stored as GPS seconds-of-week (global_encoding bit 0 = 0; values 0 to 604800 s, e.g. 601614.001126072), LAS 1.2 PDRF 1 gps_time copied as stored in file record order. The values sit at a different binary exponent and mantissa resolution than adjusted-standard time (~2^19 vs ~2^27), and week rollover is possible
- Source: https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/USGS_LPC_TX_Lubbock_2011_LAS_2016/
- Resources: https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/USGS_LPC_TX_Lubbock_2011_LAS_2016/laz/, https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/USGS_LPC_TX_Lubbock_2011_LAS_2016/0_file_download_links.txt, https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/USGS_LPC_TX_Lubbock_2011_LAS_2016/TX_Lubbock_2011.vpc, https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/USGS_LPC_TX_Lubbock_2011_LAS_2016/laz/USGS_LPC_TX_Lubbock_2011_l99757268_LAS_2016.laz
- License: US Government Public Domain (USGS 3DEP / The National Map)
- License evidence: https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/usgs-lidar.yaml
- License quote: License: US Government Public Domain https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map
- Natural record: One delivered LAZ tile = one sample: the gps_time field of every point record in stored order. Bounded subset of about 16-20 tiles, pinned by name, size and SHA-256 from the 3,574-tile project (median about 2.4 M points per tile per the VPC pc:count)
- Estimated samples: 18
- Estimated primary values: 43,000,000
- Estimated download bytes: 170,000,000
- Estimated primary bytes: 344,000,000
- Decode path: curl the pinned .laz tiles from rockyweb (slow host: use curl -C - with retry and speed-limit). Decode with tools/laz/laszip.py: compressor 2 point-wise chunked (chunk 50000), POINT10 v2 + GPSTIME11 v2 items [(6,20,2),(7,8,2)]. Take bytes 20..27 of each 28-byte PDRF-1 record as little-endian float64. Pure stdlib. The VPC JSON gives per-tile point counts for tile selection
- Novelty kind: new_quantity
- Measurement type: laser_range
- Instrument line: usgs_3dep_airborne_lidar_las12_pdrf1
- Archive collection: rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects
- Novelty evidence: No local family holds GPS week time: dc_lidar_2015_gps_time_f64 is adjusted-standard (~1.1e8 s) LAS 1.4 PDRF 6. Week time spans 0 to 6.05e5 s, so the exponent, high bytes and ULP grid (5.8e-11 s vs 1.5e-8 s) all differ, which is the shape the focus asked for. novelty.py --url on the project path finds nothing in local, registry, ledger or downstream. The only 3DEP registry entry, usgs_3dep_las_intensity_u16, was superseded (a u16 intensity field, a different quantity), and its retry_condition only redirects intensity to the DC recipe
- Homogeneity: One 2011 project (VPC datetime 2011-03-01), one LAS layout (1.2 PDRF 1, scale 0.001, global_encoding 0 = week time, written by Global Mapper), one quantity. Take tiles only from this project and only those with ge=0 headers. The builder should check the header and reject any tile whose global_encoding differs
- Risks: rockyweb.usgs.gov is slow and flaky: probes took 12-20 s and failed intermittently, and S3 prd-tnm has no mirror of these LAZ objects (404). The download needs robust retries. Week-time rollover inside a tile creates a discontinuity, which is native. Sensor and pulse rate are not yet confirmed (the metadata directory listing is empty). Some tiles have 0 points (VPC min 0); exclude them. The decode is about 12 minutes at 60k points/s for about 43M points
- Probe evidence: Range GET header of l99757268 tile: LAS1.2 pf=1 rl=28 npts=707848 ge=0 (week time), sw='Global Mapper', laszip compr=2 chunk=50000 items=[(6,20,2),(7,8,2)] (v2 items, which laszip.py supports). The first raw point's gps_time, read with an 80-byte range at the point-data offset, is 601614.001126072, which confirms seconds-of-week. The laz/ directory listing has 3,574 files, 32.8 GB total, median 9.35 MB. The VPC (10.4 MB) gives a median pc:count of 2,407,635. By contrast, the 2011 Hendricks Co IN project was checked and found to be adjusted-standard (ge=1), so it was not chosen

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_64bit/scout.20261008_211441.jsonl`).
