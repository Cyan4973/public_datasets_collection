# Terra MODIS MOD10A1 v061 daily 500 m NDSI snow cover (u8)

Draft recipe that collects complete, source-native `uint8` `NDSI_Snow_Cover`
grids from the Terra MODIS MOD10A1 Collection 6.1 daily snow product via the
Microsoft Planetary Computer COG mirror (`modis-10A1-061`).

- **Natural record:** one complete 2400 × 2400 MODIS sinusoidal tile for one
  day (463.3 m cells), one byte per cell, exactly as stored.
- **Scope:** 70 tile-days, covering 28 tiles at about 30–70° N on 10 dates
  (the 1st and 15th of each month from 2023-12-01 to 2024-04-15). Each
  sample holds 5,760,000 values, for 403,200,000 primary bytes in total.
  The download is 128.8 MB (70 COGs).
- **Homogeneity:** one sensor (Terra MODIS), one product and version
  (MOD10A1.061), one variable (`NDSI_Snow_Cover`), one fixed grid, and one
  value encoding. Excluded: Aqua MYD10A1, whose band-6 failure changes the
  algorithm, plus the albedo, QA and raw NDSI layers, the 8-day MOD10A2
  product, and MOD10A1F. Each of these would be a different family.

## Values and missing data

Per the MOD10A1 v061 user guide (Table 1) and each file's embedded `Key`
attribute:

| value | meaning |
|---|---|
| 0–100 | NDSI snow cover: 100 × NDSI of the day's best observation. 0 = snow-free land, including detections reversed by the C6.1 screens (for example NDSI < 0.1). |
| 200 | missing data |
| 201 | no decision |
| 211 | night |
| 237 | inland water |
| 239 | ocean |
| 250 | cloud |
| 254 | detector saturated |
| 255 | fill |

The flag codes are part of the native variable and are kept in place without
remapping. Build and verify reject any value outside this set. They also
reject any sample whose full grid has a valid (0..100) fraction below 0.40
or a snow (1..100) fraction below 0.02, and duplicate or degenerate grids.
Verify additionally requires at least 5% of pixels to change between
consecutive observations of the same tile.

Daily snow maps are cloud-limited by nature. Even the selected tiles keep a
lot of cloud (header cloud percent of land runs up to 49%), plus ocean along
coasts. The flag codes are therefore a large share of each sample, and the
NDSI values are the information-dense part.

## Selection rule (deterministic, no hand-picking)

1. **Candidate pool:** every Terra MOD10A1.061 item in sinusoidal rows
   v02–v05 (about 30–70° N; 82 tiles per date, fewer on 2024-04-01 and
   2024-04-15, where 1 and 4 tiles have no item) on the 1st and 15th of
   each month, 2023-12-01 to 2024-04-15. That is 815 items, all listed in
   `scripts/probe_candidates_20261006.tsv`.
2. **Rule** (`scripts/select_plan.py`): keep an item when
   - its 300 × 300 overview has an estimated valid (0..100) fraction of at
     least 0.45, and
   - its producer header attribute `SNOWCOVERPERCENT` is at least 5.
3. Nothing else: no ranking, no per-tile caps, and no item added or removed
   by hand. `verify.sh` re-runs the rule on the committed probe table and
   requires the result to equal `sources.tsv`.

Why these two signals:

- The overviews are GDAL-resampled. Averaging snow-free land (0) with cloud
  (250) fabricates values in 1..100, so overview snow estimates are badly
  inflated. On one probed tile (h11v05, 2023-12-15) the estimate was 7.9%
  against a real full-grid 0.07%. The overview valid-fraction estimate held
  up: 0.535 against 0.536 on that tile, and 0.515–0.565 against
  0.542–0.573 on three more.
- `SNOWCOVERPERCENT` is computed by the MODAPS PGE on the full grid. Three
  spot checks with header value 5 measured snow/land = 5.1%, 5.3% and 5.0%,
  where land means all pixels except ocean and inland water. On fully
  snow-covered tiles it sums with `QAPERCENTCLOUDCOVER.1` to about 100.

Two adjustments were made to the rule, both before any download run:

- The first draft used the overview snow estimate (≥ 0.05). The h11v05 spot
  check above showed it was unreliable, and the header attribute replaced it.
- The valid threshold was set to 0.45 rather than 0.50 after looking at the
  probe table. At 0.50 the rule kept 53 items on 22 tiles and no European
  tile. At 0.45 it keeps 70 items on 28 tiles, adding h19v04, h20v02,
  h20v03, h12v03 and h24v03.

The result is 70 items:

- 7 North American tiles (11 samples)
- 3 tiles on Europe's eastern and southern edge (3 samples): Balkans,
  central European Russia, northern Urals
- 18 Asian tiles (56 samples)

Clear-sky snow days are far more frequent over the dry Central Asian and
Tibetan highlands and the continental Siberian interior than over maritime
Europe or eastern North America, so Asia dominates. h25v05 alone
contributes 7 tile-days. Western and central Europe (Alps, Scandinavia)
never met the valid-fraction threshold on these dates.

## Realized output (build of 2026-10-06)

All 70 pinned items built and verified. Per-sample values come from the full
2400 × 2400 grids and are also recorded in `index/<id>/samples.jsonl` and
`filtered/<id>/ingest_stats.json`. Ranges below are min / median / max over
the 70 samples.

- **Valid (0..100) fraction:** 0.470 / 0.589 / 0.917. Every sample is at or
  above its overview estimate, by +0.007 to +0.124, so the estimate was
  conservative and no item came near the 0.40 floor.
- **Snow (1..100) fraction:** 0.049 / 0.163 / 0.728. Snow values span the
  full 10..100; the low-NDSI screen sends NDSI < 0.1 to 0.
- **Cloud (250):** 0.03 / 0.37 / 0.49.
- **Other codes:**
  - ocean (239) up to 0.32, inland water (237) up to 0.16;
  - night (211) is absent from every sample;
  - fill (255) is 12–16% on the two h24v02 samples (source-native, kept) and
    at most 0.35% elsewhere;
  - no decision (201) reaches 2.4% on h24v05 2024-01-01.
- **Distinct values per sample:** 77–92 valid values, plus 4–6 flag codes.
  Missing data (200) and detector saturated (254) never exceed 107 and 162
  pixels per sample.
- **Shannon entropy:** 1.16 / 2.43 / 5.29 bits/value.
- **zlib-6 compression:** output is 5.4% / 15.4% / 44.6% of raw size.
- **Same-tile pairs:** 35–93% of pixels change between consecutive selected
  dates of the same tile (42 pairs).
- **Header snow percent:** measured snow/land is within 4.3 percentage
  points of `SNOWCOVERPERCENT` on every sample.

Per tile and date, as fractions of the full 5,760,000-pixel grid. Areas are
approximate, for orientation only.

| tile | center lat, lon | approx. area | n | date: valid / snow / cloud fraction of the full grid |
|---|---|---|---|---|
| h08v05 | 35, -116 | Sierra Nevada / southern California | 1 | 2024-01-15: 0.54 / 0.08 / 0.24 |
| h09v04 | 45, -120 | Cascades / Columbia plateau | 1 | 2024-03-15: 0.61 / 0.26 / 0.06 |
| h09v05 | 35, -104 | southern Rockies | 2 | 2023-12-15: 0.59 / 0.16 / 0.41; 2024-03-01: 0.82 / 0.08 / 0.17 |
| h10v04 | 45, -106 | northern Rockies / northern Great Plains | 2 | 2024-02-01: 0.58 / 0.13 / 0.42; 2024-03-15: 0.80 / 0.17 / 0.20 |
| h11v03 | 55, -113 | Alberta-Saskatchewan prairie and boreal | 2 | 2024-02-15: 0.50 / 0.46 / 0.49; 2024-04-01: 0.56 / 0.25 / 0.43 |
| h11v04 | 45, -92 | Upper Midwest | 1 | 2024-03-01: 0.48 / 0.10 / 0.46 |
| h12v03 | 55, -96 | Manitoba / Hudson Bay lowlands | 2 | 2023-12-15: 0.55 / 0.55 / 0.45; 2024-04-15: 0.50 / 0.37 / 0.49 |
| h19v04 | 45, 21 | Balkans / Carpathians | 1 | 2024-02-01: 0.47 / 0.07 / 0.40 |
| h20v02 | 65, 59 | northern Urals / Pechora | 1 | 2024-02-15: 0.50 / 0.50 / 0.43 |
| h20v03 | 55, 44 | central European Russia | 1 | 2024-03-15: 0.51 / 0.50 / 0.49 |
| h21v02 | 65, 83 | northern West Siberian plain | 2 | 2024-02-15: 0.63 / 0.63 / 0.37; 2024-04-15: 0.53 / 0.53 / 0.47 |
| h21v03 | 55, 61 | southern Urals / southern West Siberia | 2 | 2024-02-15: 0.73 / 0.73 / 0.27; 2024-04-15: 0.73 / 0.15 / 0.26 |
| h21v04 | 45, 50 | Caspian / western Kazakhstan | 2 | 2024-03-01: 0.52 / 0.22 / 0.31; 2024-04-01: 0.62 / 0.06 / 0.20 |
| h21v05 | 35, 43 | Zagros / eastern Anatolia | 4 | 2023-12-15: 0.54 / 0.05 / 0.44; 2024-01-01: 0.49 / 0.05 / 0.49; 2024-03-01: 0.56 / 0.06 / 0.40; 2024-04-01: 0.92 / 0.06 / 0.03 |
| h22v02 | 65, 106 | Central Siberian plateau | 2 | 2024-03-01: 0.67 / 0.67 / 0.33; 2024-03-15: 0.65 / 0.65 / 0.35 |
| h22v04 | 45, 64 | Kazakhstan / Aral | 3 | 2024-01-15: 0.53 / 0.38 / 0.47; 2024-03-01: 0.57 / 0.22 / 0.42; 2024-03-15: 0.55 / 0.06 / 0.45 |
| h22v05 | 35, 55 | Alborz / Kopet Dag | 1 | 2024-03-01: 0.55 / 0.12 / 0.40 |
| h23v02 | 65, 130 | Yakutia | 3 | 2024-03-01: 0.69 / 0.69 / 0.29; 2024-03-15: 0.57 / 0.57 / 0.41; 2024-04-01: 0.57 / 0.57 / 0.42 |
| h23v04 | 45, 78 | Tien Shan / Balkhash | 2 | 2024-03-01: 0.57 / 0.49 / 0.43; 2024-04-01: 0.68 / 0.14 / 0.31 |
| h23v05 | 35, 67 | Hindu Kush | 6 | 2023-12-01: 0.76 / 0.08 / 0.23; 2024-01-01: 0.58 / 0.09 / 0.40; 2024-02-01: 0.54 / 0.19 / 0.46; 2024-02-15: 0.73 / 0.12 / 0.27; 2024-03-15: 0.80 / 0.24 / 0.19; 2024-04-01: 0.83 / 0.14 / 0.17 |
| h24v02 | 65, 154 | Kolyma / northeast Siberia | 2 | 2024-04-01: 0.63 / 0.63 / 0.24; 2024-04-15: 0.58 / 0.58 / 0.26 |
| h24v03 | 55, 113 | Transbaikalia | 1 | 2024-02-01: 0.54 / 0.54 / 0.45 |
| h24v04 | 45, 92 | Altai / western Mongolia | 3 | 2023-12-01: 0.52 / 0.25 / 0.47; 2024-01-15: 0.55 / 0.32 / 0.44; 2024-03-01: 0.64 / 0.29 / 0.36 |
| h24v05 | 35, 79 | Karakoram / western Tibet | 6 | 2023-12-15: 0.67 / 0.12 / 0.32; 2024-01-01: 0.73 / 0.09 / 0.24; 2024-01-15: 0.64 / 0.07 / 0.35; 2024-02-15: 0.80 / 0.14 / 0.20; 2024-03-15: 0.73 / 0.18 / 0.27; 2024-04-01: 0.64 / 0.11 / 0.36 |
| h25v04 | 45, 106 | central Mongolia | 2 | 2023-12-01: 0.71 / 0.26 / 0.29; 2024-01-15: 0.59 / 0.44 / 0.41 |
| h25v05 | 35, 92 | central Tibetan plateau | 7 | 2023-12-01: 0.74 / 0.13 / 0.25; 2023-12-15: 0.56 / 0.17 / 0.42; 2024-01-01: 0.62 / 0.06 / 0.37; 2024-01-15: 0.54 / 0.05 / 0.45; 2024-02-15: 0.79 / 0.15 / 0.21; 2024-03-01: 0.62 / 0.11 / 0.37; 2024-03-15: 0.64 / 0.09 / 0.35 |
| h26v04 | 45, 120 | Inner Mongolia / Greater Khingan | 3 | 2023-12-01: 0.71 / 0.53 / 0.28; 2024-02-15: 0.69 / 0.33 / 0.31; 2024-03-15: 0.68 / 0.15 / 0.32 |
| h26v05 | 35, 104 | eastern Tibet / Qilian | 5 | 2023-12-01: 0.62 / 0.05 / 0.37; 2024-01-01: 0.59 / 0.09 / 0.41; 2024-01-15: 0.57 / 0.05 / 0.42; 2024-03-01: 0.56 / 0.21 / 0.44; 2024-03-15: 0.54 / 0.09 / 0.46 |

## Novelty

- `tools/autocollect/novelty.py --url .../modis-061-cogs/MOD10A1/ --terms
  NDSI MOD10A1 "snow cover"` finds only same-host matches:
  `modis_active_fire_mask_u8` (MOD14A2 fire classes),
  `mpc_modis_mod13a1_ndvi_i16` (MOD13A1 NDVI) and the staging draft
  `mpc_modis_mod15a2h_fpar_u8` (MOD15A2H FPAR). Those are different
  products, quantities and files. The terms have no hits in recipes, the
  registry, or the downstream corpus.
- The nearest local family is `noaa_ims_snow_ice_cover_u8`. IMS is an
  analyst-blended 4 km categorical snow/ice/land/water code grid, not a
  per-pixel satellite NDSI retrieval at 500 m.
- `noaa_cdr_seaice_conc_nh_daily_u8` is also a 0–100-plus-flags uint8
  fraction grid, but of passive-microwave sea-ice concentration on a 25 km
  polar grid. The screener flagged that 8-bit EO fraction grids already
  have two new families this round, so this candidate is lower priority in
  breadth terms.
- Novelty kind: new quantity (fractional snow index) in a known modality
  (EO rasters).

## License

The STAC collection's `license` field is `proprietary`. Its `rel=license`
link, titled "Use and Copyright | National Snow and Ice Data Center", is
<https://nsidc.org/data/data-programs/nsidc-daac/citing-nsidc-daac>, which
says: "Data hosted by the NSIDC DAAC are openly shared, without restriction,
in accordance with NASA's Earth Science program Data and Information
Guidance. NASA data are freely accessible; however, when you publish these
data or works based on the data, you should clearly cite the data in your
research."

NASA Earthdata *Data Use Guidance*
(<https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance>)
says: "Unless the content is marked with a use restriction or license, data
provided from a NASA-led mission are licensed as Creative Commons Zero
(CC0). While there are no restrictions on the use of these data, data users
are very strongly urged to cite the data used in their work products."

MOD10A1 is NASA Terra mission data. The product page and user guide add "As
a condition of using these data, you must cite the use of this data set",
which is a citation condition and is preserved below. The citing page's
"may not be resold" sentence applies to NSIDC website photographs and
images, not to data products.

Cite: Hall, D. K. and G. A. Riggs. 2021. MODIS/Terra Snow Cover Daily L3
Global 500m SIN Grid, Version 61. Boulder, Colorado USA. NASA NSIDC DAAC.
<https://doi.org/10.5067/MODIS/MOD10A1.061>

## Run

From the repository root:

```bash
bash staging/mpc_modis_mod10a1_ndsi_snow_cover_u8/download.sh   # ~128.8 MB, 70 COGs
bash staging/mpc_modis_mod10a1_ndsi_snow_cover_u8/build.sh
bash staging/mpc_modis_mod10a1_ndsi_snow_cover_u8/verify.sh
```

- `download.sh` fetches only the 70 URLs pinned in `sources.tsv`.
  - **Access.** The container needs the anonymous, read-only SAS signature
    that Planetary Computer issues to anyone at
    `/api/sas/v1/token/modiseuwest/modis-061-cogs`. That endpoint sometimes
    answers with non-JSON, so the request retries with exponential backoff.
    The signature is cached in a mode-700 directory, refreshed every 20
    minutes and after any failed transfer, and never printed.
  - **Transfers.** They are resumable (`curl -C -`, with stall detection).
    Each file must match its pinned byte size and Azure
    `x-ms-blob-content-md5`.
  - **Header checks.** Every header must then show the expected structure
    and stable metadata: SHORTNAME `MOD10A1`, VERSIONID `61`, platform
    `Terra`, granule ID, tile numbers, observation date, DOI, `long_name`,
    `Key`, `_FillValue` 255, `missing_value` 200, `valid_range` 0..100. QA
    percentages and counts are deliberately not checked, since they vary
    per granule.
  - **Receipts.** Finally, SHA-256 receipts are written.
- `build.sh` (`scripts/build_samples.py` + `scripts/mod10a1_cog.py`) decodes
  IFD0 only and ignores the 1200/600/300 overviews.
  - It inflates the 25 Deflate tiles with exact-length checks, crops the
    edge padding (2400 = 4 × 512 + 352), and writes the unchanged uint8 grid
    row-major.
  - It also writes `index/<id>/samples.jsonl`, with min, max, sum and
    per-class counts computed from the stored bytes, plus
    `filtered/<id>/ingest_stats.json`.
- `verify.sh` (`scripts/verify_samples.py`) checks the output independently.
  - It re-derives `sources.tsv` from the probe table with the selection rule.
  - It recomputes every statistic from the sample bytes and applies the same
    missing-value policy.
  - It re-decodes every source COG with a separately written TIFF reader and
    requires byte-identical grids.
  - It checks the realized scope against the plan and the manifest, rejects
    duplicates, and requires consecutive observations of a tile to differ.

## Discovery and tests

`scripts/probe.py` documents how the plan was resolved.

- It runs one STAC `/search` per date over `modis:vertical-tile` 2..5, which
  fits on one page. It keeps IDs that start with `MOD10A1.A<YYYYDDD>.` and
  have platform `terra`; Aqua items match the same query.
- It range-reads each COG's first 64 KB (header plus the 300 × 300 overview)
  and records:
  - size and MD5,
  - structure and metadata checks (all 815 candidates pass both),
  - `SNOWCOVERPERCENT`, `QAPERCENTCLOUDCOVER.1` and `PRODUCTIONDATETIME`,
  - overview class-fraction estimates.
- Item IDs include the production timestamp. If NSIDC/MODAPS reprocesses a
  granule, the pinned URL or MD5 stops matching and `download.sh` fails
  instead of silently substituting another file.
- 2024-05-01 and 2024-05-15 were also probed while exploring, but they lie
  outside the declared season grid and are not part of the rule or the
  committed probe table.

Tests:

- **Synthetic COGs.** Both decoders were self-tested on synthetic 2400²
  COGs with the same layout: 512² tiles, random edge padding, GDAL ghost
  leaders and trailers, three overviews, and GDAL metadata. Both were
  byte-exact. The tests also confirmed rejection of a wrong tile, a wrong
  date, the Aqua platform, a changed `Key`, truncation, a corrupt Deflate
  tile, and a value (150) outside the code set. A scratch copy of the recipe
  then ran `build.sh` and `verify.sh` end to end on three synthetic tiles,
  and verify rejected a tampered sample.
- **Real files.** Four real candidate COGs were fetched and decoded during
  authoring. Three of them are pinned (the lowest-snow items h21v05
  2023-12-15, h25v05 2024-01-15 and h26v05 2024-01-15); the fourth is
  h11v05 2023-12-15, the spot check that changed the rule. Both decoders
  agreed byte for byte, all values were in the code set, and
  `--check-headers` passed on the pinned three.
- **Information content.** The three pinned files measured:
  - valid fraction 0.542–0.573, snow fraction 0.050–0.052;
  - 89–95 distinct values;
  - Shannon entropy 1.59–1.67 bits/value;
  - zlib-6 output 7.5–7.7% of raw size.

  This is low-entropy material. Large uniform cloud and snow-free regions
  sit next to fine-grained NDSI texture. That is inherent to daily snow maps
  and is the main quality caveat of this family. Across all 70 built
  samples, entropy has a median of 2.43 bits/value and zlib-6 output a
  median of 15.4% (see Realized output); the three spot files sit at the
  low end.
