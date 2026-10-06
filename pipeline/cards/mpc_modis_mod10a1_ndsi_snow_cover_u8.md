# Terra MODIS MOD10A1.061 Daily NDSI Snow Cover 500 m Sinusoidal Tiles UInt8

- Candidate id: `mpc_modis_mod10a1_ndsi_snow_cover_u8`
- Width: uint8
- Quantity: NDSI snow cover (0-100, Normalized Difference Snow Index scaled x100 after screening) per 500 m cell, with source-native flag codes in the same byte (200 missing, 201 no decision, 211 night, 237 inland water, 239 ocean, 250 cloud, 254 detector saturated, 255 fill)
- Source: https://planetarycomputer.microsoft.com/dataset/modis-10A1-061
- Resources: https://planetarycomputer.microsoft.com/api/stac/v1/collections/modis-10A1-061, https://planetarycomputer.microsoft.com/api/stac/v1/search, https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs, https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD10A1/
- License: NASA EOSDIS open data (CC0 for NASA-led mission data); NSIDC DAAC 'openly shared, without restriction'
- License evidence: https://nsidc.org/data/data-programs/nsidc-daac/citing-nsidc-daac
- License quote: Data hosted by the NSIDC DAAC are openly shared, without restriction, in accordance with NASA's Earth Science program Data and Information Guidance. (NASA Earthdata Data Use Guidance, https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance: 'Unless the content is marked with a use restriction or license, data provided from a NASA-led mission are licensed as Creative Commons Zero (CC0).')
- Natural record: One MOD10A1 granule's NDSI_Snow_Cover COG = one complete 2400x2400 uint8 sinusoidal tile for one day. Suggest Terra only, about 30 snow-zone land tiles (Rockies, Great Plains/Canada, Alps, Scandinavia, Siberia, Central Asia/Himalaya, Patagonia) x 4 dates across one snow season (e.g. 2024 DOY 015, 046, 074, 105) = about 120 samples.
- Estimated samples: 120
- Estimated primary values: 691,200,000
- Estimated download bytes: 80,000,000
- Estimated primary bytes: 691,200,000
- Decode path: Same pure-stdlib COG path as the accepted modis_active_fire_mask_u8: parse IFD0 (2400x2400, bps 8, Compression 8 Deflate, Predictor 1, 512x512 tiles, GDAL_NODATA 255), zlib-inflate the 25 tiles, crop edges, emit row-major native uint8. No remapping: snow values 0-100 and flag codes 200-255 are kept as stored. Validate that the value set is within {0..100, 200, 201, 211, 237, 239, 250, 254, 255}.
- Novelty kind: new_quantity
- Novelty evidence: novelty.py --url modiseuwest.../MOD10A1/: 'same host only' (modis_active_fire_mask_u8 = MOD14A2 FireMask, mpc_modis_mod13a1_ndvi_i16 = MOD13A1 NDVI; different products and source files). Terms NDSI/MOD10A1 had no hits anywhere, including downstream. The only 8-bit snow raster is noaa_ims_snow_ice_cover_u8: an analyst-blended 4 km categorical snow/ice/land/water code grid, not a per-pixel fractional NDSI retrieval at 500 m. Sentinel-2 SCL has only a snow class. Cryosphere is a driver focus domain; this is a new quantity there.
- Homogeneity: Single sensor (Terra MODIS; exclude Aqua MYD10A1, whose band-6 failure changes the algorithm), single product and version (MOD10A1.061), single variable, fixed 2400x2400 sinusoidal tile lattice, one value semantics. Flag codes are part of the native variable encoding, not mixed regimes.
- Risks: Low entropy: compressed COGs are 42 KB to 1.6 MB for 5.76 MB rasters (cloud, ocean and night flags dominate some tiles). Choose snow-season land tiles by a documented deterministic rule, and optionally require a minimum count of valid 0-100 pixels, rather than hand-picking. A fourth recipe on the MPC modis-061-cogs container (two accepted already), though a different product and quantity. SAS token endpoint occasionally returns non-JSON when hit rapidly: retry with backoff (seen once during the probe). The MPC collection 'license' field says 'proprietary' but its license link is the NSIDC page quoted.
- Probe evidence: STAC collection modis-10A1-061: NDSI_Snow_Cover asset uint8 COG, temporal 2000-02-24..open. Search of 2024-02-01 for h18v04 returned MOD10A1.A2024032.h18v04.061.2024034085807 with href .../MOD10A1/18/04/2024032/..._NDSI_Snow_Cover.tif. With the SAS token, a range 0-32767 gave 206, Content-Range bytes 0-32767/259335. IFD0: 2400x2400, bps 8, compression 8, predictor 1, tiles 512x512, nodata '255'. HEAD sizes for 2024-02-15 Terra tiles: h10v04 647,499 B; h12v04 708,060; h23v04 198,612; h25v05 1,601,511; h19v03 210,987; h08v04 41,785.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_8bit/scout.20261005_234256.jsonl`).
