# mpc_usda_cdl_confidence_u8

USDA NASS Cropland Data Layer (CDL) **2021 confidence layer**: the per-pixel
percent confidence (0..100) of the CDL crop/land-cover classification at
30 m. The recipe collects 51 complete 3000x3000 tiles from the Microsoft
Planetary Computer `usda-cdl` collection, spread over seven US agricultural
regions. Each tile is one raw uint8 sample of 9,000,000 values; the total is
459,000,000 bytes.

## Material

- Product: USDA NASS CDL, confidence layer (`2021_30m_confidence_layer_*`),
  the `confidence` asset of STAC items `cropland_2021_<x>_<y>_90000`.
- Meaning: for 2023 and older CDLs, NASS describes the confidence layer as
  the predicted confidence "based upon the rule(s) that were used to classify"
  the pixel, "expressed as a percentage of confidence" (0 = always wrong,
  100 = always right). It comes from the decision-tree classifier, so values form
  a discrete set of rule confidences. Probe tiles have about 85 distinct
  values, with 100 as the mode and most mass in 60..99. CDL 2024 and later
  use a random-forest MULTIPROBABILITY output instead. Only 2021 is
  collected, so there is one classifier vintage.
- Grid: EPSG:5070 (NAD83 Conus Albers), 30 m, 3000x3000 pixels = 90 km
  tiles. The GeoTIFF tie point equals the item ID origin (y + 30 m).
- Nodata: 0 (STAC `raster:bands` nodata = 0), used outside the classified
  area (ocean, large lakes). Inland land tiles have essentially no zeros.

Never mixed in: the `cropland` class codes (a categorical label raster, which
the separate draft `usda_cdl_crop_classes_u8` covers from CropScape), the
`cultivated` and `frequency` layers, the per-crop frequency assets, and any
other year.

## Licence

USDA NASS CDL FAQ/metadata page
(https://www.nass.usda.gov/Research_and_Science/Cropland/sarsfaqs2.php,
which the STAC collection's `rel=license` link points to):

> PUBLIC RELEASE: The USDA NASS Cropland Data Layer is considered public
> domain and free to redistribute.

> Use_Constraints: The USDA NASS Cropland Data Layer and the data offered on
> the CroplandCROS website is provided to the public as is and is considered
> public domain and free to redistribute.

The same page calls the Confidence Layer "a derivative of the CDL". The STAC
`license: proprietary` field is only a pointer to that link. Access is
anonymous: Planetary Computer issues a short-lived SAS signature at
`/api/sas/v1/token/landcoverdata/usda-cdl` without an account.

## Scope and selection (scripts/probe.py)

1. `probe.py list`: STAC `/search`, `usda_cdl:type = cropland`, datetime in
   2021, returned 1,095 items.
2. `probe.py screen`: seven region boxes (tile bbox fully inside). Up to 18
   candidates per region, evenly spaced in (x, y) order, giving 125
   candidates. For each candidate the probe fetched the COG header and four
   full-resolution 512x512 primary tiles (grid positions (1,1), (1,4), (4,1),
   (4,4)) by HTTP range request, and recorded the zero share, the share of
   100, distinct values and the mean (`scripts/probe_screen_20261009.tsv`).
   The COG overviews are **average-resampled**: for Iowa 163905_2182575 the
   share of 100 is 0.694 at full resolution but 0.247 in the 375x375
   overview, so overviews were not used to screen the value distribution.
3. `probe.py pin`: a candidate was eligible if its screen zero share was
   <= 0.02 and its screen share of 100 was <= 0.70. Per region, 8 tiles were
   pinned evenly spaced in item-ID order (Palouse/Columbia has only 3 tiles
   inside its box, and all 3 are kept). Each pinned blob's Content-Length and
   Content-MD5 come from a HEAD request (`sources.tsv`).

| region | tiles | screen share of 100 |
|---|---|---|
| corn_belt (IA/IL/IN/MO/WI) | 8 | 0.32-0.63 |
| plains_wheat (KS/OK/TX panhandle) | 8 | 0.11-0.57 |
| northern_plains (ND/SD/MN) | 8 | 0.24-0.54 |
| delta (AR/MS/LA) | 8 | 0.16-0.52 |
| central_valley (CA) | 8 | 0.21-0.47 |
| palouse_columbia (WA/ID/OR) | 3 | 0.30-0.48 |
| southeast (GA/AL/SC/NC) | 8 | 0.13-0.36 |

Before download, a full-tile overview check (an overview zero means the whole
8x8 block is nodata) found no nodata blocks in 48 tiles. Three coastal tiles
have about 5% open ocean: central_valley -2266095_1822575 and
-2266095_1912575 (Monterey Bay) and southeast 1423905_1282575 (Charleston).

## Scripts

- `download.sh`: validates the plan offline (51 rows, region set, URL
  derived from the item ID, MD5 format). It then requests the anonymous SAS
  signature, refreshed every 20 minutes and never printed, and fetches each
  blob with `curl -fL -C - --retry 10 --speed-limit 1024 --speed-time 120`
  into `.part` files. Each file must match its pinned size, Content-MD5 and
  TIFF magic. `scripts/cdl_cog.py --check-headers` then checks the structure
  (3000x3000, uint8, SampleFormat 1, Deflate, predictor 1 via tag 317,
  512x512 tiles, 36 non-empty in-bounds tiles, overview chain, NAD83 Conus
  Albers citation, 30 m pixel scale) and that the tie point matches the item
  ID. Finally it writes SHA-256 receipts. Expected download: 364,924,830 bytes.
- `build.sh` (`scripts/build_samples.py`, decoder `scripts/cdl_cog.py`): for
  each tile it re-checks size, MD5 and receipt SHA-256, inflates the 36
  tiles (exact 262,144-byte lengths), crops the 6x6 grid to 3000x3000 and
  writes `samples/<id>/usda_cdl_2021_confidence_u8/<item_id>_3000x3000.u8.bin`.
  A tile is fatal if it has a value above 100, a zero share above 0.10, a
  largest single-value share above 0.78, fewer than 40 distinct values, or
  duplicates another tile. It writes `index/<id>/samples.jsonl` (standard
  fields plus region, bbox, origin, statistics and hashes) and
  `filtered/<id>/ingest_stats.json`.
- `verify.sh` (`scripts/verify_samples.py`): uses an independent TIFF reader
  that does not import the build decoder. It re-decodes every source and
  requires byte equality with the sample, then recomputes and compares the
  index statistics. It re-applies the same 0..100, nodata and mode-share
  policy, checks the tie point against the item ID, the per-region counts
  (8/8/8/8/8/3/8) and the manifest sample count and total bytes, and rejects
  duplicates.

Decoders were self-tested on a synthetic 3000x3000 tiled Deflate TIFF with
random tile padding and an overview IFD, and on a real probe tile (both
decoders byte-identical). A corrupted Deflate tile is rejected by both.

## Caveats

- This is model metadata about a classification rather than a direct
  physical measurement. It is nevertheless a native, published NASS product
  layer with ordinal meaning (percent confidence).
- Value 100 dominates monoculture areas. Selection keeps every tile under a
  0.78 single-value share (screen estimate up to 0.63). Realized build
  (2026-10-09): every tile's mode is 100, with share 0.13-0.69 per tile
  (max 0.6927, Corn Belt -16095_2182575; next 0.6066, Plains
  -376095_1822575) and 0.369 overall. Per-tile distinct values 83-91,
  nonzero range 11..100. Zero share is 0.0000 except the three coastal
  tiles (0.048, 0.053, 0.049), 0.0029 overall. 51 samples, 459,000,000
  bytes.
