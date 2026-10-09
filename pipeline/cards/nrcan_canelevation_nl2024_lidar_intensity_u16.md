# NRCan CanElevation LiDAR Point Clouds, FHIMP/PICAI Newfoundland UTM21 2024 Project: Native Per-Point Return Intensity UInt16

- Candidate id: `nrcan_canelevation_nl2024_lidar_intensity_u16`
- Width: uint16
- Quantity: LAS 1.4 point-format-6 per-point laser return intensity (uint16, offset 12) from one NRCan Flood Hazard Identification and Mapping Program airborne lidar project (Newfoundland, UTM zone 21, 2024)
- Source: https://open.canada.ca/data/en/dataset/7069387e-9986-4297-9f55-0288e9676947
- Resources: https://canelevation-lidar-point-clouds.s3.ca-central-1.amazonaws.com/?list-type=2&prefix=pointclouds_nuagespoints/NRCAN/FHIMP_PICAI_NL_Newfoundland_UTM21_2024/, https://canelevation-lidar-point-clouds.s3.ca-central-1.amazonaws.com/pointclouds_nuagespoints/NRCAN/FHIMP_PICAI_NL_Newfoundland_UTM21_2024/NL_Newfoundland_20240923_NAD83CSRS_UTM21_1km_E5880_N51886_CLASS.copc.laz, https://canelevation-lidar-point-clouds.s3-ca-central-1.amazonaws.com/pointclouds_nuagespoints/CanElevation-LiDARPointClouds_products_specs_EN.pdf
- License: Open Government Licence - Canada (ca-ogl-lgo)
- License evidence: https://open.canada.ca/data/api/action/package_show?id=7069387e-9986-4297-9f55-0288e9676947
- License quote: LiDAR Point Clouds - CanElevation Series | license: Open Government Licence - Canada; 'The LiDAR point cloud data is licensed under an open government license'
- Natural record: One 1 km x 1 km CLASS COPC LAZ tile = one sample: that tile's full intensity stream
- Estimated samples: 12
- Estimated primary values: 80,000,000
- Estimated download bytes: 650,000,000
- Estimated primary bytes: 160,000,000
- Decode path: Anonymous S3 ListObjectsV2 on canelevation-lidar-point-clouds (ca-central-1) prefix .../FHIMP_PICAI_NL_Newfoundland_UTM21_2024/ (6,548 tiles, 576.7 GB; sizes p10 21 MB, p25 61 MB, median 82 MB). Pin ~12 tiles of ~40-60 MB with size+sha256; curl -C -. Python: tools/laz/laszip.py iter_chunks (PDRF 6, rl 30), '<H' at offset 12; little-endian uint16 .bin per tile. Verified decode of a 4.1 MB tile from this project.
- Novelty kind: new_source
- Measurement type: laser_range
- Instrument line: NRCan FHIMP/PICAI airborne topographic lidar, Newfoundland 2024 project
- Archive collection: NRCan CanElevation LiDAR Point Clouds (canelevation-lidar-point-clouds S3)
- Novelty evidence: No CanElevation/NRCan recipe, registry row, ledger row or downstream family (novelty.py checks for lidar sources only surfaced the DC 2015 families). Statistics differ from dc_lidar_2015_intensity_u16 (0..255): this project stores full-range scaled intensity 16,771..65,535 with 1,615 distinct values in 100k points and H 10.4 bits, plus a saturation spike at 65535.
- Homogeneity: One project folder (one acquisition/delivery, all tiles stamped 20240923, one UTM zone). Do not mix other CanElevation projects (Manitoba 2024 tile showed a different range 24,341..65,535, H 8.6; projects come from different contractors/sensors).
- Risks: Sensor model not yet confirmed from project metadata (Metadata_PointCloud_NRCAN.gdb.zip is a file-geodatabase; tile headers/VLRs or the projects index zip may name it). Tiles are COPC octree order. Saturated 65535 share is small (~0.4%) but should be reported. If IGN and this candidate are both built, zlsim may judge them against each other; their value ranges differ (≈300-7442 vs ≈16.8k-65.5k).
- Probe evidence: Bucket listing live; project listing paged fully (6,548 keys). Downloaded one 4,085,425-byte tile (E5880_N51886): LAS 1.4 PDRF 6, no RGB; decoded 100k points: intensity 16,771..65,535, 1,615 distinct, H 10.39 bits. open.canada.ca package_show confirms ca-ogl-lgo for the CanElevation series and lists the S3 bucket as the download directory.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_211441.jsonl`).
