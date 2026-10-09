# Sentinel-2 Collection-1 L2A Sen2Cor Snow Probability (MSK_SNWPRB, SNW_20m) over Glaciated/Seasonal-Snow MGRS Tiles, UInt8 Percent

- Candidate id: `earthsearch_s2c1_l2a_snow_probability_u8`
- Width: uint8
- Quantity: Per-pixel snow probability (0-100 %) from the Sen2Cor snow/ice detection, at 20 m on the 5490x5490 MGRS tile grid
- Source: https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a
- Resources: https://earth-search.aws.element84.com/v1/search, https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/32/T/LR/2024/3/S2B_T32TLR_20240319T103221_L2A/SNW_20m.tif, https://sg.geodatenzentrum.de/public/gdz/lizenz/eng/Sentinel_Data_Legal_Notice_eng.pdf
- License: Copernicus Sentinel data legal notice (free, full and open; reproduction, distribution, adaptation allowed with attribution 'Contains modified Copernicus Sentinel data [Year]')
- License evidence: https://sg.geodatenzentrum.de/public/gdz/lizenz/eng/Sentinel_Data_Legal_Notice_eng.pdf
- License quote: EU law grants free access to Copernicus Sentinel Data and Service Information for the purpose of the following use in so far as it is lawful: (a) reproduction; (b) distribution; (c) communication to the public; (d) adaptation, modification and combination with other data and information
- Natural record: One SNW_20m COG per Sentinel-2 L2A product (one MGRS tile acquisition): a full 5490x5490 uint8 raster
- Estimated samples: 24
- Estimated primary values: 723,362,400
- Estimated download bytes: 170,000,000
- Estimated primary bytes: 723,362,400
- Decode path: curl the COG; pure-stdlib TIFF parse (IFD tags 256/257/322/323/324/325), zlib-decompress each 512x512 Deflate tile (compression 8), undo horizontal predictor 2 (byte-wise cumulative sum per row), crop edge tiles to 5490x5490, write raw uint8. Verified on live files: compression 8, predictor 2, spp 1, bps 8, 11x11 tiles.
- Novelty kind: new_quantity
- Measurement type: geo_product_raster
- Instrument line: sentinel2_msi_sen2cor_snow_probability
- Archive collection: e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a
- Novelty evidence: novelty.py: no recipe, registry, ledger or downstream match for snow probability / MSK_SNWPRB / SNW_20m. The only Sentinel-2 recipes are sentinel2_l2a_scene_classification_u8 (SCL class codes, a different asset file, from sentinel-cogs) and sentinel2_l2a_reflectance_cogs_u16. Read-only zlsim feature probe (tools/autocollect/zlsim.py sample_features + percentile_distance against the 8-bit library) on decoded middle tile rows of 6 scenes (Alps T32TLR/T32TMS, Patagonia T18FXL, Alaska T06VWR/T06VVR, Norway T32VLP): nearest is local mpc_modis_mod10a1_ndsi_snow_cover_u8 at 0.0627-0.0638, then bam_read_mapq_u8 0.077-0.081, which is above the 0.05 redundancy distance.
- Homogeneity: One product line (Sentinel-2 C1 L2A, Sen2Cor, 20 m SNW asset), one quantity (snow probability %), one tile grid. Select full-footprint scenes (s2:nodata_pixel_percentage == 0) with eo:cloud_cover < 15 and s2:snow_ice_percentage between ~25 and ~75, over distinct glaciated or seasonal-snow MGRS tiles (Alps, Himalaya, Andes/Patagonia, Alaska, Scandinavia, Rockies), one scene per tile, within one season window (e.g. 2024). Don't mix S2A/S2B/S2C processing baselines across collections: use only the C1 collection.
- Risks: Bimodal values (0 and 100 dominate, about 35-60% each in sampled strips), so the mode share is high but stays under 0.8 when scenes sit within the snow-percentage window. STAC lists nodata=0, which is ambiguous with 0% snow; requiring full-footprint tiles avoids swath-edge fill. Shares product lineage with the accepted SCL recipe (different asset file and quantity); a judge might call it same-product. Only feature distance was probed; OpenZL compression-equivalence was not measured. 24 scenes x 30.1 MB = 723 MB is under the 1 GB cap; the builder may take fewer (16-20) if needed.
- Probe evidence: Earth Search STAC search returned 5,703 C1 L2A scenes for Mar-Apr 2024 with cloud<10 and snow 30-75%. HEAD on SNW_20m.tif returned 200, Content-Length 7,082,213, and a one-byte range GET with -L returned 206. TIFF header shows 5490x5490, 512x512 tiles, Deflate+predictor 2. Decoded strips have 101 distinct values (0-100).

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_110648.jsonl`).
