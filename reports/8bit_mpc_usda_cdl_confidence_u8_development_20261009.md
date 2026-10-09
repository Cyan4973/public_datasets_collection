# USDA NASS CDL 2021 confidence layer uint8 development

## Outcome

Accepted `mpc_usda_cdl_confidence_u8`. It holds complete 3000 × 3000 tiles of the USDA NASS Cropland Data Layer (CDL) 2021 **confidence layer**, taken from the Microsoft Planetary Computer `usda-cdl` COG mirror and emitted as source-native uint8.

Each value is the per-pixel percent confidence of the decision-tree rule that classified that 30 m pixel. CDL 2023 and earlier use a See5 decision tree; 2024 and later switch to random-forest MULTIPROBABILITY. Only 2021 is collected, so the family has one classifier vintage.

Novelty is new content in a well-populated modality (8-bit percent geo-product rasters):
- `earthsearch_s2c1_l2a_snow_probability_u8` is another classifier-probability percent raster.
- `jrc_global_surface_water_occurrence_u8`, `mpc_modis_mod15a2h_fpar_u8` and `mpc_modis_mod10a1_ndsi_snow_cover_u8` are other 0..100 percent rasters.

No CDL product or crop-classification confidence family exists locally, in the registry, in the ledger or downstream. The staging draft `usda_cdl_crop_classes_u8` holds categorical CDL class codes from CropScape ZIPs, which is a different quantity, file and host. Zlsim measured breadth OK: the nearest family is downstream `census_pums_usual_hours_worked_u8` at 0.056.

## Source and rights

- Source: STAC collection `usda-cdl` on Planetary Computer. The objects are the `confidence` asset of items `cropland_2021_<x>_<y>_90000`, stored in container `landcoverdata/usda-cdl/tiles/` as `2021_30m_confidence_layer_<x>_<y>_90000.tif`.
- Pinned objects: 51 exact item IDs. `sources.tsv` pins each one's Content-Length and Content-MD5, and SHA-256 receipts are written at download time.
- Download bytes: 364,924,830.
- Access: the anonymous read-only SAS signature from `/api/sas/v1/token/landcoverdata/usda-cdl`, with no account or key. It is stored in a mode-700 directory, refreshed every 20 min and never logged.
- License: public domain. The STAC `rel=license` link points to the NASS CDL FAQ (`sarsfaqs2.php#Section3_5.0`), and USDA NASS is listed as producer and licensor. The FAQ reads:
  - "PUBLIC RELEASE: The USDA NASS Cropland Data Layer is considered public domain and free to redistribute."
  - "Access_Constraints: none"
  - "Use_Constraints: ... considered public domain and free to redistribute"
  - "The Confidence Layer is a derivative of the CDL."
- Citation: USDA NASS Cropland Data Layer 2021.

## Shape and conversion

Each natural record is one complete Planetary Computer tile of 3000 × 3000 pixels: 90 km × 90 km at 30 m in EPSG:5070 NAD83 Conus Albers. The GeoTIFF tie point equals the item ID origin, with y offset by 30 m. Tiles sit on the national CDL pixel grid, so no resampling is involved.

Stored values:
- 1..100: confidence in percent. In practice only 11..100 occur.
- 0: the declared nodata (STAC `raster:bands` nodata 0, GDAL nodata 0), preserved in place.

The decoder reads only IFD0: uint8, SampleFormat 1, Deflate, Predictor 1, and 36 tiles of 512². It inflates each tile with exact-length checks, crops the edge padding (3000 = 5 × 512 + 440), and writes row-major (y, x) uint8. It does no rescaling, remapping, resampling or concatenation, and ignores the 1500/750/375 overviews.

Build and verify both treat the following as fatal:
- any value in 101..255
- a zero share above 0.10
- a largest single-value share above 0.78
- fewer than 40 distinct values
- duplicate grids
- size or MD5 mismatches
- unexpected TIFF structure, CRS citation, pixel scale or tie point
- corrupt Deflate streams

Scope and selection:
- Seven region boxes; a tile's bbox must lie fully inside its box.
- `probe.py` screened 100 candidates (18/18/18/12/13/3/18), evenly spaced in (x, y) order. Each was screened on four full-resolution 512² tiles. The overviews are average-resampled and understate the share of 100, so they were not used.
- Eligibility required a screen zero share ≤ 0.02 and a share of 100 ≤ 0.70. That excluded only 2 + 5 candidates.
- 8 tiles per region were pinned, evenly spaced in item-ID order. Palouse/Columbia has only 3 tiles inside its box, and all 3 are kept.

| Region | Tiles |
|---|---|
| corn_belt (IA/IL/IN/MO/WI) | 8 |
| plains_wheat (KS/OK/TX panhandle) | 8 |
| northern_plains (ND/SD/MN) | 8 |
| delta (AR/MS/LA) | 8 |
| central_valley (CA) | 8 |
| palouse_columbia (WA/ID/OR) | 3 |
| southeast (GA/AL/SC/NC) | 8 |

## Accepted output

| Metric | Value |
|---|---|
| Primary samples | 51 |
| Values per sample | 9,000,000 (3000 × 3000) |
| Primary values / bytes | 459,000,000 |
| Value span | 0 (nodata), 11..100 |
| Distinct values per sample | 83–91 (91 overall; 81 present in every tile) |
| Mode | 100 in every tile; share 0.127–0.693 per tile (max Corn Belt -16095_2182575), 0.369 overall |
| Nonzero mean per sample | 68.5 (Southeast) – 92.5 (Corn Belt) |
| Zero (nodata) share | 0 in 48 tiles; 0.048 / 0.053 / 0.049 in three coastal tiles (Monterey Bay ×2, Charleston); 0.0029 overall |
| Shannon entropy H0 | 2.61–5.84 bits/value (median 4.56) |
| zlib-6 ratio | 0.337–0.734 (median 0.570) |

- Global histogram: quasi-periodic rule-confidence bumps near 51, 62, 72, 83 and 92–93. Values 97–99 are nearly empty, and 100 holds 36.9%.
- Aggregate decoded SHA-256 (samples concatenated in index order): `b8d7169576dce934f3b7f4413a13619ab16199332b77bf72318f1eb636c9b490`

## Judge checks

- **Gate:** `gate.py staging/mpc_usda_cdl_confidence_u8` passes with no warnings (51 samples, median 9,000,000 values, width 8).
- **Verify:** I ran `verify.sh` myself (exit 0, about 49 s). Its separate TIFF reader re-decoded all 51 COGs and got byte-identical grids. Statistics, tie points, region counts (8/8/8/8/8/3/8) and totals also matched.
- **Build is local-only:** `build.sh` reads only `sources.tsv`, the receipts and the local rasters. Every script predates the driver's 12:57 download run (51 fetched and validated, 51 headers ok). Only README.md was edited afterwards, at 13:10.
- **Independent decode:** my own struct/zlib reader decoded two tiles (Corn Belt and Monterey Bay) byte-identical to the samples.
- **Bytes:** I inspected all 51 samples with standard-library Python.
  - **Orientation:** against each source's own 375 × 375 GDAL overview, 8 × 8 block means agree to a mean absolute difference of 0.33–0.41 DN, versus 8.8–12.6 DN transposed.
  - **No upsampling:** equality rates for even and odd column pairs are identical.
  - **Seams:** neighbour differences across the 512-pixel tile seams match interior control lines.
  - **Padding crop:** the last row and column hold 67–78 distinct values, so the crop is right.
  - **Nodata:** coastal zeros are 99% interior to zero blocks, so they are contiguous ocean.
  - **The value 100:** its share is highest in Corn Belt monoculture (0.69) and lowest in the forested Southeast (0.13–0.19). It is therefore a genuine top confidence, not a fill or burn-in flag. No fill warning was raised.
- **Selection:** I reproduced the screen from `scripts/probe_screen_20261009.tsv`. There are 100 candidates, not the 125 the README states. The share-of-100 cap removed only 2 Corn Belt candidates, so it introduces little bias.
- **License:** I fetched the STAC collection and the NASS FAQ myself. The public-domain release and the "derivative of the CDL" wording are present as quoted.
- **Novelty:** I ran `novelty.py` for the URLs, the terms and the breadth keys. There are no CDL or confidence-layer families locally, in the registry, in the ledger or downstream. Zlsim measured OK (0.056).
- **Secrets:** no SAS signature appears in any recipe file, TSV or log (grep for `sig=`/`sv=`/`se=`). `staging/*`, including `__pycache__`, is gitignored.
- **Documentation errors (no output impact):** README.md says 125 candidates were screened; the screen file has 100. The `scripts/probe.py` docstring says "six agricultural region boxes"; the code has seven. Both are worth correcting when convenient.
