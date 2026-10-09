# Sentinel-2 C1 L2A Sen2Cor Snow Probability (SNW_20m), uint8

Draft `uint8` recipe. Each sample is one complete 5490x5490 Sen2Cor
snow-probability grid (percent, 0-100, 20 m pixels) from a Sentinel-2
Collection-1 Level-2A product. That is the ESA `MSK_SNWPRB_20m` layer,
published by Element84 Earth Search as the `snow` asset `SNW_20m.tif`.
There are 30 samples, each from a different MGRS tile, acquired March-April
2024.

The recipe decodes typed raster values. It does not keep GeoTIFF bytes. The
build parses IFD0 of each COG, inflates the 121 Deflate tiles, undoes the
horizontal predictor 2, crops the padded edge tiles, and writes the uint8
grid row-major (y, x) with no value changes.

## Run

```bash
bash staging/earthsearch_s2c1_l2a_snow_probability_u8/download.sh   # 274,844,184 bytes, 30 COGs
bash staging/earthsearch_s2c1_l2a_snow_probability_u8/build.sh
bash staging/earthsearch_s2c1_l2a_snow_probability_u8/verify.sh
```

`DATA_DIR` (default `.data`) is honoured. Logs go to
`$DATA_DIR/logs/earthsearch_s2c1_l2a_snow_probability_u8/`.

## Source and license

- Collection: Earth Search `sentinel-2-c1-l2a`, processing baseline 05.10
  only. The recipe does not use the older `sentinel-s2-l2a-cogs` or
  `sentinel-cogs` products. Assets are in the public bucket
  `e84-earth-search-sentinel-data` (us-west-2; no account or payment needed),
  fetched over anonymous HTTPS.
- License: [Legal notice on the use of Copernicus Sentinel Data and Service
  Information](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice).
  The STAC collection links this notice as `rel=license`, and so does the AWS
  Registry of Open Data entry. Quote: "EU law grants free access to Copernicus
  Sentinel Data and Service Information for the purpose of the following use
  in so far as it is lawful: (a) reproduction; (b) distribution;
  (c) communication to the public; (d) adaptation, modification and combination
  with other data and information".
- Attribution: **Contains modified Copernicus Sentinel data 2024.**

## Pinned resources and selection

`sources.tsv` pins each item ID, MGRS tile, acquisition time, cloud and
snow percentages, header statistics, byte size, SHA-256 (the STAC
`file:checksum` multihash with its `1220` prefix stripped) and exact URL.
`download.sh` does not use a live STAC search. It checks size, SHA-256, the
TIFF magic and the exact TIFF layout.

The plan was resolved on 2026-10-09 by two documentation scripts.
`scripts/discover.py` pages through the STAC API using keyset `next` tokens.
`scripts/select_plan.py` applies the selection rule:

1. Query: collection `sentinel-2-c1-l2a`, 2024-03-01..2024-04-30,
   `eo:cloud_cover < 15`, `s2:nodata_pixel_percentage == 0`,
   `25 <= s2:snow_ice_percentage <= 75`. This returns 1,785 items on 1,184
   MGRS tiles, all baseline 05.10.
2. Drop tiles with |centroid latitude| > 72. Keep one scene per MGRS tile:
   the one whose snow % is closest to 50, ties broken by lower cloud.
3. Group tiles into cells of 10 deg latitude x 20 deg longitude and keep cells
   with at least 3 tiles. For the 4 tiles closest to 50 % snow in each cell,
   read the COG header with a 4 KB range request. The GDAL statistics there are
   written with nodata=0, so `STATISTICS_VALID_PERCENT` is the nonzero share.
   Keep the tile whose nonzero share is closest to 0.5, within 0.30-0.75.
4. Take the 30 cells with the most tiles.

The result is 30 scenes on 30 MGRS tiles in 30 cells, all in the Northern
Hemisphere, latitude 29-62 N. Regions: Coast Mountains/Cascades/Sierra
Nevada, the Canadian Shield and taiga, Quebec, Karelia and the Russian
plain, the Caucasus and Zagros, Tian Shan and Altai, the Himalaya and the
Tibetan plateau, Mongolia, Siberia, Amur/Sakhalin, Hokkaido and Kamchatka. No
Alpine or Southern Hemisphere tile was selected, because those cells have too
few qualifying tiles in this window.

| item | tile | lat | lon | SCL snow % | header nonzero share |
|---|---|---|---|---|---|
| S2A_T09UXT_20240405T193749_L2A | MGRS-9UXT | 51.83 | -126.75 | 51.5 | 0.514 |
| S2A_T10TFN_20240314T185255_L2A | MGRS-10TFN | 42.84 | -121.10 | 55.7 | 0.504 |
| S2A_T10TGM_20240314T185255_L2A | MGRS-10TGM | 41.92 | -119.93 | 51.1 | 0.475 |
| S2A_T11SKC_20240410T185302_L2A | MGRS-11SKC | 38.32 | -119.80 | 54.1 | 0.512 |
| S2A_T15UVP_20240403T171803_L2A | MGRS-15UVP | 48.26 | -93.61 | 48.0 | 0.444 |
| S2A_T36VUL_20240303T092328_L2A | MGRS-36VUL | 59.02 | 30.47 | 49.3 | 0.429 |
| S2A_T44RPT_20240318T051126_L2A | MGRS-44RPT | 29.33 | 82.60 | 50.9 | 0.461 |
| S2A_T45TUL_20240311T052052_L2A | MGRS-45TUL | 45.54 | 85.14 | 50.2 | 0.487 |
| S2A_T46VDP_20240420T051733_L2A | MGRS-46VDP | 61.73 | 92.15 | 56.1 | 0.498 |
| S2B_T10VEN_20240420T192906_L2A | MGRS-10VEN | 60.84 | -121.99 | 51.3 | 0.439 |
| S2B_T12VWN_20240428T185658_L2A | MGRS-12VWN | 60.84 | -109.99 | 52.2 | 0.458 |
| S2B_T13VFD_20240423T180207_L2A | MGRS-13VFD | 57.22 | -102.43 | 53.2 | 0.506 |
| S2B_T15UXU_20240428T171503_L2A | MGRS-15UXU | 52.73 | -90.71 | 48.0 | 0.486 |
| S2B_T19UEQ_20240408T153554_L2A | MGRS-19UEQ | 49.16 | -68.25 | 53.0 | 0.496 |
| S2B_T36VXN_20240305T090935_L2A | MGRS-36VXN | 60.81 | 35.85 | 56.0 | 0.501 |
| S2B_T38TKK_20240403T080221_L2A | MGRS-38TKK | 40.12 | 42.12 | 53.1 | 0.499 |
| S2B_T38VLK_20240303T082915_L2A | MGRS-38VLK | 58.12 | 42.54 | 46.5 | 0.421 |
| S2B_T39SVR_20240302T072902_L2A | MGRS-39SVR | 32.04 | 50.52 | 55.0 | 0.518 |
| S2B_T43TGH_20240401T054331_L2A | MGRS-43TGH | 42.82 | 78.12 | 50.7 | 0.501 |
| S2B_T43UET_20240321T060630_L2A | MGRS-43UET | 51.85 | 75.80 | 53.7 | 0.487 |
| S2B_T44RKV_20240428T053107_L2A | MGRS-44RKV | 31.11 | 78.43 | 49.3 | 0.485 |
| S2B_T45SWT_20240426T045330_L2A | MGRS-45SWT | 33.84 | 87.59 | 50.3 | 0.486 |
| S2B_T46UED_20240409T045949_L2A | MGRS-46UED | 52.75 | 93.81 | 50.2 | 0.447 |
| S2B_T48STA_20240329T035257_L2A | MGRS-48STA | 32.02 | 102.40 | 48.0 | 0.431 |
| S2B_T48TXS_20240319T035256_L2A | MGRS-48TXS | 46.44 | 107.02 | 50.8 | 0.474 |
| S2B_T48UWF_20240414T040554_L2A | MGRS-48UWF | 54.55 | 105.85 | 49.5 | 0.467 |
| S2B_T52UGV_20240322T022328_L2A | MGRS-52UGV | 49.11 | 132.49 | 49.1 | 0.485 |
| S2B_T53UPS_20240405T015648_L2A | MGRS-53UPS | 50.94 | 137.20 | 49.9 | 0.475 |
| S2B_T54TXQ_20240327T012655_L2A | MGRS-54TXQ | 44.64 | 142.95 | 44.6 | 0.467 |
| S2B_T57UWV_20240322T003603_L2A | MGRS-57UWV | 53.65 | 159.83 | 50.3 | 0.527 |

## Decode

`scripts/snw_cog.py` is a pure-stdlib reader that accepts only this layout:
little-endian classic TIFF, 5490x5490, 8-bit unsigned, 1 sample, Deflate (8),
predictor 2, 512x512 tiles (121), `GDAL_NODATA` "0". Every tile must inflate
to exactly 262,144 bytes. Predictor 2 is undone as a running byte sum
modulo 256 along each tile row. The last tile row and column are cropped
(5490 = 10x512 + 370).

`build.sh` first runs `scripts/selftest_decoder.py`. The self-test builds a
synthetic 5490x5490 TIFF with this exact layout and junk in the edge
padding, and checks a byte-exact round trip. It also checks that a truncated
file and a predictor-1 file are rejected. The decoder was also run on one real
asset (T44RKV, 2.8 MB) during authoring. Its SHA-256 matched the STAC
checksum, the decoded nonzero share was 0.48456 against a header value of
48.46 %, and the nonzero mean was 98.1606472 against a header value of
98.16064721808.

## Value policy

- Values 0..100 (percent). The COG declares nodata = 0, which is the same
  code as "0 % snow". All selected products have
  `s2:nodata_pixel_percentage == 0`, so there is no swath-edge fill and
  every 0 is kept as a measured 0 %.
- Build and verify both require:
  - all values in 0..100
  - at least 20 distinct values
  - mode share at most 0.80
  - decoded nonzero percent within 0.005 of the header
    `STATISTICS_VALID_PERCENT` (GDAL rounds it to 2 decimals)
  - nonzero mean within 1e-6 of `STATISTICS_MEAN`
  - no duplicate grids
- `verify.sh` re-decodes every source with its own TIFF, Deflate and
  predictor code (it does not import `snw_cog`). It compares the result
  byte-for-byte with the sample, then checks the index, manifest totals and
  `ingest_stats.json`.

## Output

- 30 samples x 30,140,100 bytes = 904,203,000 bytes of primary uint8, under
  the 1 GB cap.
- `$DATA_DIR/samples/earthsearch_s2c1_l2a_snow_probability_u8/s2c1_l2a_snw_20m_snow_probability_u8/<item_id>.u8`
- `$DATA_DIR/index/earthsearch_s2c1_l2a_snow_probability_u8/samples.jsonl`
- `$DATA_DIR/filtered/earthsearch_s2c1_l2a_snow_probability_u8/ingest_stats.json`
  holds the zero, 100, intermediate and mode shares and the distinct count
  for each sample.

## Caveats

- The values are strongly bimodal. Across the 30 built grids the share of
  0 is 0.473-0.579 (median 0.514), the share of 100 is 0.126-0.487 (median
  0.362), and the share of 1..99 is 0.025-0.361 (median 0.118). Every grid
  uses all 101 values. The largest mode share is 0.579, well under the
  0.80 limit. Long runs of 0 and 100 are the nature of the layer.
- The layer comes from the same Sen2Cor processing chain as the accepted
  `sentinel2_l2a_scene_classification_u8` recipe, but it is a different asset
  and a different quantity: a continuous percentage, not class codes. That
  recipe also uses a different collection (the old `sentinel-cogs` L2A, not
  Collection-1). The nearest family by bytes is expected to be
  `mpc_modis_mod10a1_ndsi_snow_cover_u8`. The scout's feature probe put it at
  distance about 0.063. Compression equivalence was not measured before the
  build.
