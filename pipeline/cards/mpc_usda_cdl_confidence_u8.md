# USDA NASS Cropland Data Layer (CDL) 30 m Per-Pixel Classification Confidence Layer (0-100 %), Planetary Computer 3000x3000 COG Tiles, UInt8

- Candidate id: `mpc_usda_cdl_confidence_u8`
- Width: uint8
- Quantity: Per-pixel classifier confidence (percent) of the CDL decision-tree crop/land-cover prediction at 30 m
- Source: https://planetarycomputer.microsoft.com/dataset/usda-cdl
- Resources: https://planetarycomputer.microsoft.com/api/stac/v1/collections/usda-cdl, https://landcoverdata.blob.core.windows.net/usda-cdl/tiles/163905/2021_30m_confidence_layer_163905_2182575_90000.tif, https://planetarycomputer.microsoft.com/api/sas/v1/token/usda-cdl, https://www.nass.usda.gov/Research_and_Science/Cropland/sarsfaqs2.php
- License: Public domain (USDA NASS: 'considered public domain and free to redistribute')
- License evidence: https://www.nass.usda.gov/Research_and_Science/Cropland/sarsfaqs2.php
- License quote: The USDA NASS Cropland Data Layer and the data offered on the CroplandCROS website is provided to the public as is and is considered public domain and free to redistribute.
- Natural record: One MPC confidence COG tile (cropland_<year>_<x>_<y>_90000 item, 'confidence' asset): a 3000x3000 uint8 raster
- Estimated samples: 50
- Estimated primary values: 450,000,000
- Estimated download bytes: 225,000,000
- Estimated primary bytes: 450,000,000
- Decode path: Get an anonymous SAS token from https://planetarycomputer.microsoft.com/api/sas/v1/token/usda-cdl (curl), curl the COG, then do the pure-stdlib TIFF parse: Deflate tiles (compression 8, predictor 1), 512x512 tiles, 6x6 tile grid, crop to 3000x3000, write raw uint8. Verified live: compression 8, predictor 1, spp 1, bps 8.
- Novelty kind: new_quantity
- Measurement type: geo_product_raster
- Instrument line: usda_nass_cdl_classifier
- Archive collection: landcoverdata.blob.core.windows.net/usda-cdl
- Novelty evidence: novelty.py on the usda-cdl URL plus terms 'confidence layer', cropland, CDL: the only hit is the staging draft usda_cdl_crop_classes_u8, which holds crop class codes from CropScape ZIPs (a different quantity and source host). No registry, ledger or downstream family carries a classifier-confidence raster. zlsim read-only feature probe on decoded tile rows from Iowa (163905_2182575, 2021) and California Central Valley (2021): nearest is mpc_modis_mod15a2h_fpar_u8 at 0.0643, then downstream census_pums_usual_hours_worked_u8 at 0.0664 and pfam_seed_alignments_u8 at 0.0697, all above 0.05.
- Homogeneity: One product (NASS CDL confidence layer), one year (2021, so one classifier vintage), one 30 m grid and 3000x3000 tiling. Spread about 50 tiles across agricultural regions (Corn Belt, Great Plains wheat, Delta cotton/rice, Central Valley, Palouse, Southeast). Exclude tiles that are mostly nodata 0 (outside CONUS or open water) by checking STAC proj geometry or a quick nonzero share after build.
- Risks: Confidence saturates at 100 in Corn Belt monoculture (69% of one Iowa strip), so mixed-crop regions are needed to keep the mode share under 0.8. It is model metadata about a classification rather than a direct physical measurement; a strict judge could call it proxy-like, but it is a native published product layer with ordering meaning (percent confidence). The SAS-token step is needed (MPC; the same pattern as accepted MPC recipes). Agriculture is outside this round's focus domains but is an EO raster. Compression equivalence not measured.
- Probe evidence: MPC STAC search returned cropland_YYYY items carrying 'confidence' assets for 2019-2021. HEAD on the 2021 Iowa tile with SAS token returned 200, Content-Length 4,489,355. TIFF header shows 3000x3000, 512 tiles, Deflate. Decoded strips have 85-88 distinct values, with 100 the mode and a tail of 90-94.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_110648.jsonl`).
