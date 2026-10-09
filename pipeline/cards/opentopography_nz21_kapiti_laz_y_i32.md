# Kapiti Coast (Wellington, NZ) 2021 Airborne Lidar (AAM for KCDC/LINZ, via OpenTopography) Per-Tile LAS Scaled Int32 Y Record Coordinates

- Candidate id: `opentopography_nz21_kapiti_laz_y_i32`
- Width: int32
- Quantity: LAS point-record Y field: native little-endian int32 northing code (scale 0.001 m, offset 5,000,000 m, NZTM2000), one value per return in file order
- Source: https://doi.org/10.5069/G9GT5KCD
- Resources: https://opentopography.s3.sdsc.edu/pc-bulk?list-type=2&prefix=NZ21_Kapiti/&max-keys=1000, https://opentopography.s3.sdsc.edu/pc-bulk/NZ21_Kapiti/CL2_BN32_2021_500_063100.laz, https://portal.opentopography.org/datasetMetadata?otCollectionID=OT.012022.2193.1
- License: CC BY 4.0
- License evidence: https://portal.opentopography.org/datasetMetadata?otCollectionID=OT.012022.2193.1
- License quote: Dataset Acknowledgement: Released under Creative Commons CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Attribution Required for Copies: "Copyright in this work is owned by Kapiti Coast District Council" ... Use License: CC BY 4.0
- Natural record: One 500 m LAZ tile (CL2_BN32_2021_500_*.laz) = one sample: the full Y column of the tile's point records in file order
- Estimated samples: 32
- Estimated primary values: 77,000,000
- Estimated download bytes: 320,000,000
- Estimated primary bytes: 310,000,000
- Decode path: List the public S3-compatible bucket (anonymous ListObjectsV2 with continuation tokens; 3,383 .laz tiles, 39.5 GB). Choose ~32 tiles of 5-15 MB (2,585 qualify) by a deterministic rule such as every k-th key in sorted order. curl them and decode with tools/laz/laszip.py (LAS 1.4, pf6, layered compressor). Y is the int32 at record offset 4 of each 30-byte record; emit as little-endian int32.
- Novelty kind: new_source
- Measurement type: laser_range
- Instrument line: aam_airborne_lidar_nz_linz
- Archive collection: opentopography.s3.sdsc.edu/pc-bulk
- Novelty evidence: novelty.py --url opentopography.s3.sdsc.edu/pc-bulk/NZ21_Kapiti with terms kapiti/linz/opentopography: no matches in recipes, registry, ledger or downstream. No OpenTopography pc-bulk or NZ lidar source exists in the corpus, and no int32 LAS coordinates.
- Homogeneity: One survey (AAM, 13-15 March 2021, 27.95 pts/m2), one delivery (LAStools las2las, pf6), one fixed scale/offset (0.001 m; offset 1,700,000/5,000,000/0) and one CRS (EPSG:2193). Only the Y field.
- Risks: opentopography.s3.sdsc.edu sometimes drops TLS or returns empty bodies on the first try, so download.sh needs retries. Per-tile points vary (about 1-6M), and file order inside the tiles is LAStools-processed order, not necessarily flight order. Partial tiles along the coast and the survey edge have fewer points. Only one coordinate per source should be proposed (X would not be a new family).
- Probe evidence: Range GET bytes 0-8191 of CL2_BN32_2021_500_063100.laz returned 206: LAS 1.4, pf6, n=1,182,346, scale 0.001, offset (1,700,000; 5,000,000; 0), Y 5,491,320-5,491,680 m, so stored Y is about 491,320,000-491,680,000 (29 bits). The full listing gives 3,383 .laz tiles (median 9.79 MB, 39.5 GB total). The OT catalog API confirms NZ21_Kapiti, OTLAS.012022.2193.1, DOI 10.5069/G9GT5KCD.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_211441.jsonl`).
