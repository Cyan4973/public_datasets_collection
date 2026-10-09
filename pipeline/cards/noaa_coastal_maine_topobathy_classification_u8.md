# NOAA NGS 2022-23 Coastal Maine Topobathymetric Lidar (NV5, Leica Chiroptera HawkEye 4X, COPC LAS 1.4 PDRF 6): Per-Point Topobathy Classification UInt8

- Candidate id: `noaa_coastal_maine_topobathy_classification_u8`
- Width: uint8
- Quantity: LAS 1.4 PDRF-6 classification byte under the ASPRS topobathy domain profile: 1 unclassified, 2 ground, 7 low noise, 18 high noise, 40 bathymetric bottom, 41 water surface, 42 derived water surface, 43 submerged object, 45 water column, 64 submerged aquatic vegetation, 65 submerged temporal exclusion, in COPC file order
- Source: https://coast.noaa.gov/dataviewer/#/lidar/search/where:ID=10423
- Resources: https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/?list-type=2&prefix=laz/geoid18/10423/, https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/10423/metadata_2022_ngs_coastalMaine.xml, https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/10423/block02_03/20221121_523500e_4906000n.copc.laz, https://registry.opendata.aws/noaa-coastal-lidar/
- License: NOAA open data (NODD): open to the public, use as desired; US Government work
- License evidence: https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/noaa-coastal-lidar.yaml
- License quote: License: NOAA data disseminated through NODD are open to the public and can be used as desired. ... NOAA requests attribution for the use or dissemination of unaltered NOAA data. Metadata: "Access Constraints: None".
- Natural record: One 500 m x 500 m COPC tile (e.g. block02_03/20221121_523500e_4906000n.copc.laz) gives one sample: its full per-point classification array in the file's stored (octree-node) point order.
- Estimated samples: 20
- Estimated primary values: 125,000,000
- Estimated download bytes: 850,000,000
- Estimated primary bytes: 125,000,000
- Decode path: curl the pinned tiles → tools/laz/laszip.py (COPC: compressor 3, lazperf variant, variable chunk size -1 with chunk table; the README validates COPC PDRF 6/7 with variable chunks; about 63k points/s) → byte 16 of each 30-byte PDRF-6 record → uint8 .bin per tile.
- Novelty kind: new_source
- Measurement type: laser_range
- Instrument line: airborne_topobathy_lidar_las
- Archive collection: noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/10423
- Novelty evidence: novelty.py --url .../laz/geoid18/10423/ with the terms 'topobathy', 'Chiroptera' and 'coastal lidar': no matches. No manifest uses noaa-nos-coastal-lidar-pds. The existing dc_lidar_2015_classification_u8 is a topographic urban code set (1-17). This family's values are dominated by bathymetric classes 40/41/45/64/65, absent from the corpus, from a green-laser bathymetric sensor regime. Order differs too: COPC octree order versus DC flight order.
- Homogeneity: One project (NOAA NGS 2022-23 Coastal Maine, InPort/DAV ID 10423), one contractor (NV5), one sensor model (Leica Chiroptera HawkEye 4X), one class scheme stated in the lineage, one format (COPC LAS 1.4 PDRF 6). 44,316 tiles in 10 blocks. Suggested subset: 2 shoreline tiles from each block (20 tiles of 30-50 MB). One field only.
- Risks: Inland or all-land tiles carry only topographic classes and would look like the DC classification family. The builder should choose shoreline or nearshore tiles, for example by requiring that decoded class 40/41 share exceed a documented threshold, or by using the project tile index, and state the selection rule. That is a content-based selection the judge may scrutinise. Classification is a categorical code rather than a magnitude; the corpus accepts it (DC classification and land-cover u8 families), but the byte gate could still call it redundant. COPC octree order is the published file order, not acquisition order. Large tiles (median 41.7 MB, about 6M points) mean roughly 30 min of decoding for 20 tiles. The project metadata carries a generic 'removed 10 days after 2025-09-12' compile notice, but the bucket objects were live on 2026-10-08.
- Probe evidence: S3 listing of laz/geoid18/10423/: 44,316 .copc.laz, 1.79 TB, median 41.7 MB (p10 18.4, p90 56.8), blocks block01_01 to block04_03. One-byte range GET returned 206. Header: LAS1.4 pf6 rl30 n=6,182,373, ext byret=[5078358,877773,195817,...]; VLRs copc info, then laszip compressor 3 'lazperf variant' chunk -1, then LASF_Projection. The metadata XML lineage names the sensor ('collected by NV5 using Leica Chiroptera Hawkeye 4X systems ... LAS format 1.4, point data record format 6') and the class list (40 bathymetric point, 41 water surface, 42 derived water surface, 43 submerged object, 45 water column, 64 submerged vegetation, 65 submerged temporal exclusion).

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_211441.jsonl`).
