# Terra MODIS MOD13A1 v061 16-Day 500 m NDVI Int16 Tiles

- Candidate id: `mpc_modis_mod13a1_ndvi_i16`
- Width: int16
- Quantity: MODIS Terra 16-day composite Normalized Difference Vegetation Index (MOD13A1.061, band 500m_16_days_NDVI), native int16 scaled by 0.0001 (valid -2000..10000, fill -3000), 500 m sinusoidal grid.
- Source: https://planetarycomputer.microsoft.com/api/stac/v1/collections/modis-13A1-061
- Resources: https://planetarycomputer.microsoft.com/api/stac/v1/search, https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs, https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD13A1/12/04/2024193/MOD13A1.A2024193.h12v04.061.2024212093349_500m_16_days_NDVI.tif, https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD13A1/21/09/2024193/MOD13A1.A2024193.h21v09.061.2024212093118_500m_16_days_NDVI.tif
- License: CC0-1.0 (NASA-led mission data via LP DAAC / Earthdata data-use guidance)
- License evidence: https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance
- License quote: Unless the content is marked with a use restriction or license ... data provided from a NASA-led mission are licensed as Creative Commons Zero (CC0).
- Natural record: One complete MOD13A1 NDVI tile for one 16-day composite period: a 2400 x 2400 int16 grid (h/v sinusoidal tile). Proposed scope: 12 land-dominant tiles across all continents (e.g. h08v05, h10v04, h12v04, h12v10, h13v12, h18v04, h19v08, h20v11, h21v09, h25v05, h28v05, h31v11) x 2 periods (2024 DOY 017 and DOY 193) = 24 samples. Terra (MOD) only.
- Estimated samples: 24
- Estimated primary values: 138,240,000
- Estimated download bytes: 240,000,000
- Estimated primary bytes: 276,480,000
- Decode path: Same proven path as accepted modis_active_fire_mask_u8: anonymous MPC SAS token via curl, STAC search on modis-13A1-061 with query modis:horizontal-tile / modis:vertical-tile (ints) and datetime. Filter IDs starting with 'MOD13A1' (the platform property is empty on older items). Take asset 500m_16_days_NDVI and pin item IDs and sizes. Download with curl. Pure-Python TIFF: little-endian classic TIFF, 2400x2400, BitsPerSample 16, SampleFormat 2 (signed), Compression 8 (Deflate), Predictor 1, 512² tiles (25), GDAL nodata -3000. zlib per tile, crop edge tiles, emit row-major LE int16.
- Novelty kind: new_quantity
- Novelty evidence: novelty.py --url .../collections/modis-13A1-061 --terms NDVI MOD13Q1 'vegetation index': no term matches in recipes, registry, ledger or downstream. URL matches are only the shared MPC STAC host used by modis_active_fire_mask_u8 (MOD14A2 FireMask, 8-bit class grid, a different product and file) and sentinel1_grd_measurement_u16. No vegetation-index family exists locally or downstream at any width.
- Homogeneity: One product (MOD13A1 v061), one sensor (Terra), one layer (NDVI), one scale (0.0001), one grid (500 m sinusoidal 2400² tiles), one fill (-3000). Do not mix in EVI, Aqua MYD13A1, the 250 m MOD13Q1 or the reflectance layers; each would be a separate family. Fill (ocean/cloud) is source-native; keep it and document it, preferring land-dominant tiles.
- Risks: (1) The MPC license field says 'proprietary' but links to LP DAAC, which redirects to the Earthdata CC0 guidance. This is the same evidence chain accepted for modis_active_fire_mask_u8. (2) Coastal tiles carry large -3000 fill fractions, so choose land-dominant tiles. (3) The COG is MPC's conversion of the source HDF4-EOS SDS; values are the native int16 SDS, so cite source_field '500m_16_days_NDVI'. (4) The token is needed per run (the blob returns 409 without one).
- Probe evidence: STAC item_assets: 500m_16_days_NDVI raster:bands data_type int16. STAC search listed Terra MOD13A1 items for h12v04, h21v09, h25v05 and h31v11 at 2024 DOY 177 and 193. HEAD Content-Length 9,943,189 for MOD13A1.A2024193.h12v04. Header range read: 2400x2400, 16-bit, SampleFormat 2, Deflate, predictor 1, 512² tiles, nodata -3000. Decoding tile index 6 gave 262,144 values, min -3000, max 9970, 9,629 distinct (fill 17,973 px), so the values are dense and high-entropy. No token returns 409; an anonymous token returns 200/206.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_16bit/scout.20261005_160501.jsonl`).
