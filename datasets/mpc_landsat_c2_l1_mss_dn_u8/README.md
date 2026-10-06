# Landsat-5 MSS Collection 2 Level-1 band DN (uint8)

This recipe collects complete Landsat-5 Multispectral Scanner (MSS) scenes
from the USGS Collection 2 Level-1 archive, precision- and terrain-corrected
(processing level **L1TP**, **Tier 1**). Each sample is one band of one scene:

| band | asset | spectral range |
| --- | --- | --- |
| B1 | `green` | 0.5–0.6 µm |
| B2 | `red` | 0.6–0.7 µm |
| B3 | `nir08` | 0.7–0.8 µm |
| B4 | `nir09` | 0.8–1.1 µm |

Every sample holds the USGS calibrated, quantized top-of-atmosphere radiance
digital number (QCAL 1..255, stored as uint8) on a 60 m north-up UTM grid.
`0` is fill outside the rotated scene footprint. The source is the Microsoft
Planetary Computer `landsat-c2-l1` collection, a mirror of the USGS products.

    radiance [W m-2 sr-1 um-1] = RADIANCE_MULT_BAND_n * DN + RADIANCE_ADD_BAND_n
    (per scene and band, from the scene MTL; e.g. B1 of 186/041 1984: 0.88504 * DN + 1.51496)

The coefficients are copied into each index row as documentation and are
**not applied**.

**What this is, and what it is not.** These are orthorectified Earth-observation
multispectral rasters. USGS calibrated them radiometrically, corrected them
geometrically against ground control points and a DEM, and resampled them by
cubic convolution onto a map grid. They are **not** raw instrument or camera
frames in detector geometry. That separates them from the raw space-camera
families (Voyager ISS, IUE and similar). Residual MSS sensor character, such
as six-detector banding, can remain. MSS quantized onboard to 6 bits; bands
1–3 were companded and expanded to 7 bits in ground processing. Collection 2
rescales the calibrated values to the 1..255 QCAL range. The realized
histograms are often narrow, e.g. the p1–p99 span of Corrientes B1 is 24..41
and of Northern Territory B1 is 63..87. They are not comb-like: no band has
an empty bin inside its p1–p99 range, because the cubic-convolution
resampling fills the gaps of the coarse source quantization.

## Scope and scene rule

- **Natural record:** one scene band = one Cloud-Optimized GeoTIFF, e.g.
  `LM05_L1TP_186041_19840521_20210911_02_T1_B1.TIF`. Rasters are 3381–4262
  rows × 3761–4304 columns, depending on footprint rotation and latitude
  (IFD 0 = STAC `proj:shape` = MTL `REFLECTIVE_LINES/SAMPLES`). Each index row
  records `sample_shape = [height, width]`. Samples are whole band rasters;
  they are not tiled or sharded.
- **Path/rows:** 13 fixed WRS-2 path/rows, chosen for biome and continental
  spread and for land-dominant footprints. They are listed in `discover.sh`:

  | WRS-2 | region | biome | acquired |
  | --- | --- | --- | --- |
  | 186/041 | Fezzan, Libya | hyper-arid hamada and erg | 1984-05-21 |
  | 176/052 | Kordofan–Darfur, Sudan | Sahel savanna, dry season | 1985-03-31 |
  | 170/042 | Harrat Khaybar, Saudi Arabia | arid plateau, lava fields | 1988-08-04 |
  | 162/029 | Aral Sea west shore, Ustyurt | cold desert, shrinking lake | 1986-05-19 |
  | 104/073 | Barkly–Tanami, Australia | tropical savanna, dry season | 1991-10-18 |
  | 230/077 | Gran Chaco, Salta, Argentina | dry forest, sub-Andean ranges | 1984-09-30 |
  | 225/080 | Corrientes / Iberá, Argentina | humid grassland, wetland | 1984-08-26 |
  | 030/037 | Llano Estacado, Texas | irrigated and dryland cropland | 1986-05-06 |
  | 021/030 | Lower Michigan | temperate farmland and forest | 1986-06-08 |
  | 015/042 | South Florida, Everglades | subtropical wetland, coast | 1986-04-27 |
  | 065/011 | Mackenzie Delta, Canada | arctic delta, sea ice | 1984-06-22 |
  | 171/012 | Bolshezemelskaya tundra, Russia | arctic tundra, thermokarst lakes | 1985-07-02 |
  | 039/017 | Canadian Shield, NWT | boreal forest, glacial lakes | 1985-07-05 |

- **Selection:** per path/row, the items of `landsat-c2-l1` that meet all of:
  - `platform = landsat-5`, `instruments = ["mss"]`;
  - `landsat:correction = L1TP`, `landsat:collection_category = T1`,
    collection `02`, WRS-2;
  - item id `LM05_L1TP_<path><row>_<date>_02_T1`;
  - datetime 1984-03-01..1993-12-31;
  - `0 <= eo:cloud_cover < 5` and `view:sun_elevation > 30`;
  - all of `green`, `red`, `nir08`, `nir09` and `mtl.json` present.

  Among those, it takes the lowest cloud cover, then the highest sun
  elevation, then the earliest datetime, then the id. The realized scenes all
  have cloud cover 0, except 039/017 at 3 (the only candidate there). Sun
  elevation runs from 35.4 to 61.9°.
- **Excluded by construction:** Landsat 1–4 MSS (different instruments and
  calibration history), L1GS/L1GT products, Tier 2, and the 2012–2013 MSS
  re-activation after the TM failure. The uint16 `qa_pixel` and `qa_radsat`
  assets are a different width and quantity, and are not downloaded.
- **How the path/rows were picked:** over 1984–1993, the archive holds 1,826
  Landsat-5 MSS L1TP T1 scenes with cloud < 5, on 384 path/rows. Most of
  the US interior is Tier 2 for MSS; Kansas, for example, has no T1 scenes at
  all. Path/rows centred over open sea (Sea of Japan, Gulf of Bothnia, the
  Canaries, and others) were not considered. The remaining candidates were
  screened with the MPC rendered previews. Footprints dominated by ocean or
  cloud were dropped: NSW south coast 089/085, Ebro delta 198/032, southern
  Baltic 192/021, Hudson/James Bay 022/021, 022/022 and 032/019, and
  southern New Guinea 102/065.
  Kordofan, Northern Territory and Fezzan are bright, low-contrast dry-season
  scenes, kept as they are. The 039/017 scene carries a smoke plume and some
  cumulus in spite of its 3% cloud score.

## Realized output (build of 2026-10-06)

- **Volume:** 13 scenes × 4 bands = **52 samples**, 746,545,896 bytes
  (= values, uint8). Samples are 12,976,278–18,343,648 bytes each; the median
  holds 13,814,153 values.
- **Years:** 1984: 4 scenes, 1985: 3, 1986: 4, 1988: 1, 1991: 1.
- **Downloads:** 52 band COGs + 13 MTL.json = 65 files, 411,160,598 bytes,
  plus 117 KB of rights documents. Azure Content-MD5 is published and pinned
  for every file.
- **Fill:** per-band fill fraction runs from 0.261 (Northern Territory) to
  0.449 (Mackenzie Delta, 70° N, the most rotated footprint). Overall it is
  0.336 of all bytes.
- **Values:**
  - valid DN span 1..255 overall;
  - per band, 83 to 255 distinct valid DN (median 254.5);
  - Shannon entropy including fill 3.67–6.17 bits (median 4.99);
  - zlib-6 ratios 0.27–0.43 on spot checks.

  The flattest bands come from uniform targets: Corrientes B1 (std 4.3),
  Northern Territory B1 (std 5.2) and Gran Chaco B1 (std 6.4). The widest
  come from Mackenzie Delta B1–B2 (sea ice against open water, std 72–77) and
  Aral/Ustyurt B3 (std 72).
- **Saturation (DN 255):** kept as source values and counted per band.
  45 of 52 bands carry the MTL `SATURATION_BAND_n = Y` flag, and 39 contain
  at least one 255. Saturation is negligible except in a few bands:
  - **Fezzan B2 and B3:** 42.8% and 40.0% of valid pixels. The bright sand
    sea in the west half of the scene saturates the MSS red and NIR-1
    channels at a 62° sun.
  - Mackenzie Delta B1–B2 (sea ice): 3.9–4.6%.
  - Canadian Shield B2–B3 (smoke and cumulus) and Harrat Khaybar B2:
    about 1%.

  The two Fezzan bands are the least regular samples. They still hold
  154–167 distinct DN and 4.3–4.4 bits of entropy. A sanity cap of 60%
  saturated valid pixels per band is enforced.
- **Decode-correctness guards, realized:**
  - spatial coherence (mean |horizontal neighbour difference| / std)
    0.046–0.288;
  - band fill masks agree on ≥ 99.86% of pixels;
  - corr(B1, B2) 0.796–0.996 and corr(B3, B4) 0.833–0.998.

  A visual spot check of downsampled bands and a full-resolution crop across
  a tile corner showed no seams.

## Plan resolution and pinning

`discover.sh` resolved the plan on 2026-10-06 with metadata requests only:

- 13 STAC searches;
- an anonymous SAS;
- a HEAD per blob for Content-Length and Content-MD5;
- a 64 KiB range read of each COG header, to check IFD 0 (uint8, Deflate,
  256-px tiles, Predictor 1, GDAL_NODATA "0") against STAC `proj:shape`.

The plan is pinned as `sources.tsv`, one row per file. Asset hrefs embed the
USGS processing date (`..._19840521_20210911_02_T1_B1.TIF`), so they are
pinned verbatim.

`download.sh` uses only `sources.tsv` and requires exactly 13 scenes, 65
files and 411,160,598 bytes. It validates every file:

- exact size and pinned Content-MD5;
- for COGs: little-endian TIFF magic, the IFD-0 structure, the pinned
  shape, and a full inflate of every tile;
- for MTL.json: a semantic check. `LANDSAT_5`, `MSS`, `L1TP`, `T1`,
  collection `02`, path/row and date must match, `REFLECTIVE_LINES/SAMPLES`
  must equal the pinned shape, bands 1–4 must be `UINT8` with QCAL 1..255,
  and `ORIGIN` must credit the USGS. ORIGIN is compared with whitespace
  removed, because three of the 13 files (176/052, 170/042 and 015/042)
  write it as `ImagecourtesyoftheU.S.GeologicalSurvey`.

The SAS comes from `/api/sas/v1/token/landsateuwest/landsat-c2` (no account,
key or login). It is refreshed every 15 minutes or after a failed transfer,
with back-off. Transfers resume with `curl -C -` and are stall-bounded
(`--speed-limit 1024 --speed-time 120`), never `--max-time`. build.sh and
verify.sh refuse to run if the plan under `.data/` differs from
`sources.tsv`.

## Decode

Pure standard-library Python, in `scripts/mss_cog.py`:

- parse IFD 0: BitsPerSample 8, SampleFormat 1, Photometric 1, Compression 8,
  Predictor 1, 256 × 256 tiles, GDAL_NODATA "0";
- inflate each tile to exactly 65,536 bytes. GDAL sparse tiles read as zero.
  Predictor 2 would be undone mod 256, though none of the pinned files use it;
- copy rows into the grid and crop the right and bottom edge-tile padding to
  the per-scene width and height. Overview IFDs are ignored.

Output is the source row-major order: rows north→south, columns west→east,
bytes unchanged.

`mss_cog.py selftest` checks both decoders on synthetic TIFFs written by an
independent encoder:

- edge tiles, predictor 1 and 2, sparse tiles, and padding that must be
  cropped;
- header-only prefixes;
- rejection of 16-bit samples, LZW, missing or non-zero nodata, big-endian
  byte order, and truncated tile streams.

download.sh and build.sh run the self-test first. verify.sh re-derives every
sample with `scripts/mss_independent_decode.py`, which shares no code with
the build decoder, and byte-compares the result.

## Missing values and degeneracy guards

Fill `0` outside the footprint is preserved in place. QCAL_MIN is 1, so `0`
is never a valid DN. Saturated pixels (255) are kept and counted per band,
next to the MTL `SATURATION_BAND_n` flag. build.sh and verify.sh enforce the
same bounds, computed by different code:

- per band: ≥ 1,000,000 valid pixels; fill fraction within 0.05..0.70;
  ≥ 16 distinct valid DN with max > min; valid DN inside the MTL QCAL range;
  saturated (255) pixels ≤ 60% of valid pixels;
- spatial coherence: mean absolute horizontal neighbour difference / std
  ≤ 0.6 per band;
- per scene: the four band fill masks agree on ≥ 99% of pixels;
- decode-correctness guards: corr(B1, B2) ≥ 0.5 and corr(B3, B4) ≥ 0.5 over
  jointly valid pixels.

A mis-decoded or misplaced tile produces noise or seams, and fails the
coherence and correlation guards. The coherence, mask and saturation bounds
were tightened after the first build, from 0.9, 97% and no cap. They keep at
least a 2× margin to the realized values: max coherence 0.288, min mask
agreement 99.86%, max saturation 42.8%.

## License

- **Grant 1:** the USGS data policy
  (https://www.usgs.gov/emergency-operations-portal/data-policy). The
  Planetary Computer collection links it as its license under the title
  "Public Domain", via the older URL
  https://www.usgs.gov/core-science-systems/hdds/data-policy, which
  redirects there. It reads: "Most of the satellite images supplied by U.S.
  Federal civil agencies are public domain (such as Landsat or ASTER). … All
  public domain imagery may be used, shared, transferred, or redistributed
  without restriction. However, there should be acknowledgement of the image
  source within any derived maps, products, or publications." This is the
  same evidence relied on by the accepted `mpc_aster_l1t_tir_u16`.
- **Grant 2:** the USGS-managed AWS Open Data Registry entry "USGS Landsat"
  (https://registry.opendata.aws/usgs-landsat/, "Managed By United States
  Geological Survey"). Its License field reads: "There are no restrictions on
  Landsat data downloaded from the USGS; it can be used or redistributed as
  desired. We do request that you include a statement of the data source when
  citing, copying, or reprinting USGS Landsat data or images."
- **Provenance:** the downloaded products are USGS Collection 2 Level-1
  files. Each MTL.json carries `ORIGIN = "Image courtesy of the U.S.
  Geological Survey"` (spaces stripped in three files) and the DOI
  10.5066/P9AF14YV.
- **Captured evidence:** `download.sh` saves the MPC collection JSON
  (required) and at least one grant document under
  `downloads/mpc_landsat_c2_l1_mss_dn_u8/rights/`, before any raster
  transfer. The MPC JSON is checked for:
  - the rel=license "Public Domain" usgs.gov data-policy link;
  - NASA and USGS as licensors;
  - cite-as DOI 10.5066/P9AF14YV;
  - uint8 nodata-0 band assets and uint16 QA assets.

  `scripts/rights_check.py` phrase-checks the grant documents. Receipts
  (requested and effective URL, HTTP code, size, sha256) go to
  `rights_receipts.tsv`. `build.sh` refuses to run without ok receipts, and
  `verify.sh` re-runs the checks offline.
- **Why two grants:** usgs.gov intermittently times out or refuses curl. The
  authoring session saw 504s and timeouts, and then an HTTP 200 a few minutes
  later. The registry page is the reachable alternative, and either grant
  document is accepted.
- **Authoring-time capture (2026-10-06):**
  - MPC JSON: 10,928 bytes, sha256 `ff11d3a187eb…cc777`;
  - USGS policy page: 89,600 bytes, sha256 `86f3f2d17997…0c6`, both phrases
    matched;
  - registry page: 16,826 bytes, sha256 `51e78769e7bf…abd49`.
- **Not claimed:** the STAC `license` field reads `proprietary` and only
  points to the USGS page.

Attribution: "Landsat imagery courtesy of the U.S. Geological Survey." Cite
Landsat 1–5 MSS Collection 2 Level-1, https://doi.org/10.5066/P9AF14YV.

## Novelty

The local corpus has no full-scene optical multispectral Earth-observation
raster at 8 bits. This is a new source and a new quantity for that width.
The nearest families:

- **`statlog_landsat_satellite_u8`** (UCI Statlog): also Landsat MSS DN, but
  a tiny tabular benchmark. It holds about 6.4k rows of 3 × 3-pixel
  neighbourhoods, 36 values each, cut from one Australian scene. It contains
  no scene rasters, no spatial context beyond 3 × 3, and no fill structure.
- **`sentinel2_l2a_reflectance_cogs_u16`:** optical multispectral, but a
  different sensor, product (L2A surface reflectance), width (16-bit) and
  era.
- **`sentinel2_l2a_scene_classification_u8`** and
  **`esa_worldcover_landcover_tiles_u8`:** 8-bit EO rasters of categorical
  class codes, not radiance.
- **`nasa_pds_themis_ir_mosaic_u8`, `nasa_pds_voyager_iss_saturn_raw_u8`:**
  planetary imaging. One is a stretched Mars thermal-IR mosaic, the other
  raw camera frames. They are a different body, a different processing
  chain, and not calibrated radiance DN.
- **`mpc_aster_l1t_tir_u16`:** the same MPC access pattern and the same
  rights evidence, but thermal-IR at 16 bits.
- **`landsat8_l1tp_bayarea_multispectral_u16`** is registered as
  `needs_tooling` (Landsat-8 OLI, 16-bit, LZW). It is a different sensor and
  width, and does not overlap this recipe.

Breadth caveat: this round's accepted 8-bit families already include several
imaging modalities (SAR and radar backscatter, sonar, raw space-camera
frames, passive microwave). This family is optical multispectral reflected
sunlight over Earth's land surface, after orthorectification. It is related
to those families as "imagery", but it is a different material and
generation process.

## Run

```bash
bash staging/mpc_landsat_c2_l1_mss_dn_u8/download.sh   # 65 pinned files, 411,160,598 bytes, resumable
bash staging/mpc_landsat_c2_l1_mss_dn_u8/build.sh
bash staging/mpc_landsat_c2_l1_mss_dn_u8/verify.sh
```

`discover.sh` is optional. It re-runs the metadata-only resolution, so a fresh
result can be compared with `sources.tsv`. All scripts honour `DATA_DIR`
(default `.data`) and log to `$DATA_DIR/logs/mpc_landsat_c2_l1_mss_dn_u8/`.
