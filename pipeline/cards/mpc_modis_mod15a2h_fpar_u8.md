# Terra MODIS MOD15A2H.061 8-Day FPAR 500 m Sinusoidal Tiles UInt8

- Candidate id: `mpc_modis_mod15a2h_fpar_u8`
- Width: uint8
- Quantity: Fraction of Photosynthetically Active Radiation absorbed by green vegetation (DN 0-100, scale 0.01), retrieved by the MODIS LAI/FPAR radiative-transfer LUT algorithm, with source-native fill classes 248-255 (non-terrestrial/barren/urban/water/unclassified/fill) in the same byte
- Source: https://planetarycomputer.microsoft.com/dataset/modis-15A2H-061
- Resources: https://planetarycomputer.microsoft.com/api/stac/v1/collections/modis-15A2H-061, https://planetarycomputer.microsoft.com/api/stac/v1/search, https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs, https://modiseuwest.blob.core.windows.net/modis-061-cogs/MOD15A2H/
- License: NASA EOSDIS open data (CC0 for NASA-led mission data; LP DAAC policy)
- License evidence: https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance
- License quote: Unless the content is marked with a use restriction or license, data provided from a NASA-led mission are licensed as Creative Commons Zero (CC0). While there are no restrictions on the use of these data, data users are very strongly urged to cite the data used in their work products.
- Natural record: One MOD15A2H granule's Fpar_500m COG = one complete 2400x2400 uint8 sinusoidal tile for one 8-day composite. Suggest Terra MOD15A2H only (not MYD/MCD), about 24 land-dominant tiles on six continents x 4 composites spread over one year (e.g. 2024 DOY 017, 105, 193, 281) = about 96 samples.
- Estimated samples: 96
- Estimated primary values: 552,960,000
- Estimated download bytes: 405,000,000
- Estimated primary bytes: 552,960,000
- Decode path: Identical to the accepted MPC MODIS recipes: parse IFD0 (2400x2400, bps 8, Compression 8 Deflate, Predictor 1, 512x512 tiles, GDAL_NODATA 255), zlib-inflate the tiles, crop edges, emit row-major native uint8. Keep 0-100 values and fill codes 248-255 as stored; validate the value set.
- Novelty kind: new_quantity
- Novelty evidence: novelty.py --url modiseuwest.../MOD15A2H/: 'same host only' (MOD14A2 fire mask u8 and MOD13A1 NDVI i16 are different products and files). Terms FPAR/LAI had no hits in recipes, registry, ledger or downstream. No vegetation biophysical-variable raster (FPAR/LAI) exists at any width. It is distinct from NDVI: an RT-model inversion output on a 0-1 fraction lattice, not a band-ratio index.
- Homogeneity: Single sensor (Terra), single product/version (MOD15A2H.061), single variable (Fpar_500m), fixed tile lattice, one scale (0.01). Do not mix in Lai_500m (different quantity and scale) or MCD15A2H (combined Terra+Aqua).
- Risks: Third MODIS product from the same MPC container. The judge may weigh breadth (FPAR correlates with the already-accepted 16-bit NDVI family), which is why this is lowest priority. Fill classes over deserts, ice and oceans can dominate some tiles; prefer land-dominant tiles by a deterministic rule. The STAC 'platform' property is empty for this collection, so filter by item-id prefix 'MOD15A2H' rather than by platform.
- Probe evidence: STAC collection modis-15A2H-061 lists Fpar_500m, Lai_500m, FparLai_QC, FparExtra_QC, LaiStdDev_500m and FparStdDev_500m as uint8 COGs. A bbox search (10-11E, 47-48N) for 2024-07-11 returned MOD15A2H.A2024193.h18v04.061.2024202042310 with href .../MOD15A2H/18/04/2024193/..._Fpar_500m.tif. With the SAS token, a range 0-16383 gave 206, Content-Range bytes 0-16383/4228880 (4.2 MB compressed for 5.76 MB raw, so information-rich). IFD0: 2400x2400, bps 8, compression 8, predictor 1, tiles 512x512, sampleformat 1, nodata '255'.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_8bit/scout.20261005_234256.jsonl`).
