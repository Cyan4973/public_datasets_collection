# USGS 3DEP ID North Fork Payette 2020 (QL1, LAS 1.4 PDRF 6 LAZ): Per-Point Return Number (multi-return pulse structure over mountain conifer forest) UInt8

- Candidate id: `usgs_3dep_id_northforkpayette_laz_return_number_u8`
- Width: uint8
- Quantity: LAS 1.4 point-format-6 return number: the 4-bit ordinal (1..15, seen up to 9) of each echo within its laser pulse, taken from the low nibble of byte 14 of each POINT14 record. The same byte's high nibble, number_of_returns (echoes per pulse), can go in a second primary series of the same recipe. Both are genuine ordinal/count measurements of canopy penetration, not IDs.
- Source: https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/ID_NorthForkPayette_2020_B20/ID_NorthForkPayette_1_2020/0_file_download_links.txt
- Resources: https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/ID_NorthForkPayette_2020_B20/ID_NorthForkPayette_1_2020/0_file_download_links.txt, https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/ID_NorthForkPayette_2020_B20/ID_NorthForkPayette_1_2020/ID_NorthForkPayette_1_2020.vpc, https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/ID_NorthForkPayette_2020_B20/ID_NorthForkPayette_1_2020/LAZ/, https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/ID_NorthForkPayette_2020_B20/ID_NorthForkPayette_1_2020/metadata/USGS_LPC_ID_NorthForkPayette_2020_B20_11TLL37050010.xml
- License: US Government Public Domain (USGS 3DEP)
- License evidence: https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/usgs-lidar.yaml
- License quote: License: US Government Public Domain https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map
- Natural record: One delivered LAZ tile, i.e. all points of one 3DEP tile in file order. Use a bounded, pinned subset of about 16-24 tiles chosen from the project VPC by pc:count, ideally from the lower quartile (8-11M points) to bound decode time, spread across the project area. The project has 9,761 tiles.
- Estimated samples: 20
- Estimated primary values: 220,000,000
- Estimated download bytes: 1,300,000,000
- Estimated primary bytes: 220,000,000
- Decode path: curl the pinned rockyweb LAZ URLs (S3 prd-tnm holds only the link list, VPC and metadata, not the LAZ). Decode with tools/laz/laszip.py iter_chunks (compressor 3, POINT14 v3). Per chunk, slice byte 14 of each 30-byte record with the strided slice recs[14::rlen] and keep b & 0x0F (return number); optionally (b >> 4) for number_of_returns. Write one u8 file per tile. Validate that the per-return histogram matches the LAS 1.4 header's 15-entry extended return counts exactly.
- Novelty kind: new_quantity
- Measurement type: laser_range
- Instrument line: airborne_lidar_las_usgs3dep_ql1_pdrf6_merge
- Archive collection: rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/ID_NorthForkPayette_2020_B20
- Novelty evidence: novelty.py: no recipe, registry row or downstream family extracts LAS return number or number of returns at any width. The only 8-bit LiDAR families are dc_lidar_2015_classification_u8 (accepted) plus the queued Scotland scan-angle i8 and Maine topobathy classification u8 candidates. The rockyweb URL prefix matches staging usgs_3dep_nc_geiger_laz_x_i32, but that is a different project (NC Geiger-mode, int32 X) and a different field. Geiger-mode data has essentially single returns, so it carries no such structure. The user's priorities name multi-return structure as one of the most likely new LAZ fields.
- Homogeneity: One project (ID_NorthForkPayette_1_2020), one acquisition (2020-09-03 to 2020-10-09), one contractor pipeline (header system id 'MERGE', software 'LiDAR Suite'), LAS 1.4 PDRF 6 throughout (verified on 3 tiles spread across the link list). Terrain is uniformly Payette NF mountain conifer forest. One quantity per series.
- Risks: (1) Byte gate: the alphabet is small (1..9, about 68-79% ones per the header histograms), so it could land near dc_lidar_2015_classification_u8 (also a small-alphabet u8 with runs). The ascending 1,2,3 within-pulse pattern differs from class runs, but this is unmeasured. (2) Decode time: about 60k pts/s, so 200M+ points is about 1 h. Keep the tile count and size bounded. (3) rockyweb flakiness was seen once in the ledger (Lubbock): use curl retries and -C -. Liveness was fine today: HEAD returned 200 with content-length on 3 tiles. (4) The sensor model is not named in the FGDC metadata.
- Probe evidence: S3 link list: 9,761 LAZ URLs. VPC pc:count quartiles are 10.3M / 14.0M / 18.1M points per tile. Range GETs of the headers of tiles #1, #3000 and #7000 gave LASF 1.4, PDRF 6 (compressed), 14.3M/19.0M/17.6M points, sizes 83/102/95 MB. Extended return histograms: tile #1 (9,639,698; 3,474,526; 951,039; 173,940; 20,038; 1,465; 82; 4) and tile #7000 up to 9 returns. Metadata begdate 20200903, enddate 20201009.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_224222.jsonl`).
