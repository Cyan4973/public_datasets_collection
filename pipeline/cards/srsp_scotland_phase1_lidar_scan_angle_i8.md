# LiDAR for Scotland Phase I (Blom 2011-12, TerraScan LAS 1.2 PDRF 1): Per-Point Scan Angle Rank Int8

- Candidate id: `srsp_scotland_phase1_lidar_scan_angle_i8`
- Width: int8
- Quantity: LAS point-record scan angle rank: signed int8 whole degrees of the laser pulse off nadir, in the source point order of each tile (native PDRF-1 field at byte offset 16)
- Source: https://remotesensingdata.gov.scot/data#/list
- Resources: https://srsp-open-data.s3.eu-west-2.amazonaws.com/?list-type=2&prefix=lidar/phase-1/laz/, https://srsp-open-data.s3.eu-west-2.amazonaws.com/lidar/phase-1/laz/27700/gridded/NS5151_2PPM_LAS_PHASE1.laz, https://api.remotesensing.data.gov.scot/search/collection/scotland-gov/*
- License: Open Government Licence v3.0
- License evidence: https://api.remotesensing.data.gov.scot/search/collection/scotland-gov/*
- License quote: collection scotland-gov/lidar/phase-1/laz, useConstraints: "The following attribution statement must be used to acknowledge the source of the information: Crown copyright Scottish Government, SEPA and Scottish Water (2012). Open Government Licence v3". The portal's About page adds: "All data is made available under the Open Government Licence v3 unless otherwise stated."
- Natural record: One 1 km British National Grid LAZ tile (e.g. NS5151_2PPM_LAS_PHASE1.laz) gives one sample: that tile's full scan-angle-rank array in file point order.
- Estimated samples: 60
- Estimated primary values: 110,000,000
- Estimated download bytes: 330,000,000
- Estimated primary bytes: 110,000,000
- Decode path: curl the pinned tiles (S3 listing gives sizes and ETags) → tools/laz/laszip.py iter_chunks (compressor 2, POINT10 v2 + GPSTIME11 v2, 50,000-point chunks; byte-exact validated path, about 110k points/s) → take byte 16 of each 28-byte PDRF-1 record as int8 → write little-endian int8 .bin per tile. Pure stdlib.
- Novelty kind: new_quantity
- Measurement type: laser_range
- Instrument line: airborne_lidar_las
- Archive collection: srsp-open-data.s3.eu-west-2.amazonaws.com/lidar/phase-1
- Novelty evidence: novelty.py --url .../lidar/phase-1/laz/ with the terms 'scan angle', 'Scotland lidar' and 'phase-1': no matches in recipes, registry, ledger, downstream or downstream_registry. No srsp-open-data host appears in any manifest or ledger. The corpus's only airborne-LAS 8-bit family is dc_lidar_2015_classification_u8 (a class-code alphabet). Scan angle has never been collected at any width, and its sequence is a sweep pattern (slowly varying along scan lines, reversing at swath edges), unlike any existing 8-bit family.
- Homogeneity: One programme, one contractor (Blom), one acquisition campaign (Mar 2011 to May 2012, about 2 ppm), and one delivery format. Eight headers sampled across the 12,464-tile list were all LAS 1.2 PDRF 1, record length 28, TerraScan-written (one was re-zipped by the LASzip DLL), with at most 4 returns. Pick about 60 tiles evenly spaced across the sorted key list so all 10 collection areas are covered. One field only.
- Risks: Not verified without fetching payload: scan angle may be zero or degenerate in some tiles (verify must reject a tile whose values are constant). Point order inside a TerraScan tile is assumed to follow flight lines. Mixed-overlap tiles interleave two flight lines, which is still the natural tile order. Phase II of the same portal is Non-Commercial Government Licence: download.sh must stay inside the lidar/phase-1/ prefix. If Phase I scan angles turn out to be mostly zero, fall back to Outer Hebrides 2019 (Bluesky, TerraScan, PDRF 1, OGL v3, lidar/outer-hebrides/2019/laz/4ppm/, 1,506 tiles, median 28.8 MB).
- Probe evidence: S3 list-type=2 under lidar/phase-1/laz/: 12,464 .laz objects, 68.5 GB, median 5.03 MB (p10 2.44, p90 8.99). One-byte range GET returned 206. Header range reads: NS5151 LAS1.2 pf1 rl28 n=1,943,476 byret=(1841880,90635,10324,637,0) sw='TerraScan'; NJ2958 pf1 n=2,940,920. LASzip VLR: compressor 2, chunk 50,000. Portal API collection JSON gives the per-collection useConstraints quoted above.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_211441.jsonl`).
