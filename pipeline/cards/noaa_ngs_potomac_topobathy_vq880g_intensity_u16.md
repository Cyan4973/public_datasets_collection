# NOAA NGS 2018 Topobathy Lidar, Potomac River / Chesapeake Bay (Riegl VQ-880-G, Digital Coast ID 8727): Native Per-Point Return Intensity UInt16

- Candidate id: `noaa_ngs_potomac_topobathy_vq880g_intensity_u16`
- Width: uint16
- Quantity: Per-point laser return intensity (uint16, LAS record offset 12) of a Riegl VQ-880-G green+NIR topobathymetric lidar, NOAA NGS Coastal Mapping Program 2018 acquisition (QSI), as redistributed by NOAA OCM as COPC LAZ (PDRF 7, RGB empty)
- Source: https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/8727/index.html
- Resources: https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/?list-type=2&prefix=laz/geoid18/8727/, https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/8727/delivery01/20180217_371500e_4210500n.copc.laz, https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/8727/metadata_2018_ngs_topobathy_potomac_river_chesapeake.xml
- License: NOAA open data (US Government work; NODD: open to the public, use as desired, attribution requested)
- License evidence: https://github.com/awslabs/open-data-registry/blob/main/datasets/noaa-coastal-lidar.yaml
- License quote: NOAA data disseminated through NODD are open to the public and can be used as desired.
- Natural record: One 500 m x 500 m delivery tile (COPC LAZ) = one sample: that tile's full intensity stream
- Estimated samples: 20
- Estimated primary values: 65,000,000
- Estimated download bytes: 350,000,000
- Estimated primary bytes: 130,000,000
- Decode path: S3 ListObjectsV2 (anonymous) over laz/geoid18/8727/ (5,968 .copc.laz tiles, 322.6 GB, sizes p10 13.6 MB / median 47.7 MB); pin ~20 tiles of 10-25 MB spread across delivery01/delivery02 with size+sha256; curl -C -. Python: tools/laz/laszip.py iter_chunks (LAS 1.4 PDRF 7, rl 36), '<H' at offset 12; write little-endian uint16 .bin per tile. Verified: full decode of the 11.5 MB tile 20180217_371500e_4210500n succeeded (1,915,380 points, 27.8 s, ~69k pts/s).
- Novelty kind: new_source
- Measurement type: laser_range
- Instrument line: Riegl VQ-880-G topobathymetric airborne lidar (NOAA NGS Coastal Mapping Program)
- Archive collection: NOAA NODD noaa-nos-coastal-lidar-pds (Digital Coast)
- Novelty evidence: novelty.py --url noaa-nos-coastal-lidar-pds.../laz/geoid18/8727/ --terms topobathy coastal-lidar: no matches anywhere (local, registry, ledger, downstream). Different modality regime from dc_lidar_2015_intensity_u16 (topographic NIR, 0..255 range, 95 distinct): this is a bathymetric green+NIR Riegl full-16-bit intensity stream (0..65535, 4,535 distinct in one tile, H 9.1 bits, heavy mode around 3,800-3,950 from water-surface/column returns).
- Homogeneity: One dataset (Digital Coast ID 8727), one sensor (Riegl VQ-880-G), one contractor/processing chain (QSI RiProcess, NOAA OCM COPC conversion), one year. Points interleave the VQ-880-G green bathy and NIR channels within each tile as delivered — that is the instrument's native stream, not a mix of programs. Do not add other NOAA datasets.
- Risks: Some NOAA format-7 LAZ from other projects failed laszip decode (an Oregon ID 14002 tile raised 'chunk 0 is corrupt'); this dataset's tile decoded fully, but builder should validate every pinned tile and replace failures. Very small edge tiles (~100 KB) should be avoided. Intensity includes saturated 65535 values and zero, documented as native. Metadata boilerplate mentions dynamic compilation date; irrelevant to the LAZ objects.
- Probe evidence: Bucket listing live (anonymous ListObjectsV2). EPT/metadata: Riegl VQ-880G acquisition by QSI for NOAA NGS RSD Coastal Mapping Program, Feb-Apr 2018, LAS 1.2 PDRF 3 delivery, reprojected/sorted by OCM. Downloaded two small tiles (129 KB, 11.5 MB; < 20 MB total): header LAS 1.4 PDRF 7 rl 36; RGB all zero; intensity 0..65535, distinct 1,673 (24k pts) and 4,535 (1.9M pts), H 9.5 / 9.1 bits.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_211441.jsonl`).
