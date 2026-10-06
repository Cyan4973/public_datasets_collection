# Landsat-5 MSS Collection 2 Level-1 band DN uint8 development

## Outcome

Accepted `mpc_landsat_c2_l1_mss_dn_u8`. It holds complete Landsat-5
Multispectral Scanner (MSS) scene bands from the USGS Collection 2 Level-1
archive (L1TP, Tier 1), as mirrored by the Microsoft Planetary Computer
`landsat-c2-l1` collection. Values are the source-native uint8 calibrated,
quantized top-of-atmosphere radiance DN, with the zero fill kept in place.

This is the corpus's first full-scene optical multispectral Earth-observation
radiance raster at 8 bits. The nearest families:
- `statlog_landsat_satellite_u8`: also MSS DN, but a tiny UCI table of
  3 × 3-pixel neighbourhoods cut from one scene, with no scene rasters or
  fill structure.
- `sentinel2_l2a_reflectance_cogs_u16`: optical multispectral, but a
  different sensor and product (L2A surface reflectance) at 16 bits.
- `sentinel2_l2a_scene_classification_u8` and
  `esa_worldcover_landcover_tiles_u8`: 8-bit class codes, not radiance.
- `mpc_aster_l1t_tir_u16`: the same Planetary Computer access and rights
  chain, but thermal infrared at 16 bits.

Novelty is labelled `new_source`: MSS DN already exists in table form; the
USGS C2 L1 scene archive and full-scene raster material are new.

Breadth note: this round already accepted several 8-bit imaging modalities
(SAR, radar, sonar, raw space-camera frames, passive microwave). None of them
is reflected-sunlight optical Earth-observation radiance, so this family
adds a different material.

These are calibrated, GCP- and DEM-corrected, cubic-resampled map rasters,
not raw detector frames. Residual MSS sensor character remains: six-detector
banding, and a quantization ripple from the 6/7-bit to 8-bit rescale.

## Source and rights

- **Source:** STAC collection `landsat-c2-l1` on Planetary Computer;
  container `landsateuwest/landsat-c2/level-1/standard/mss/`.
- **Pinned objects:** 13 exact product IDs (USGS processing dates
  2020-08-27..2021-09-19 embedded). Each scene has four band COGs (B1 green,
  B2 red, B3 nir08, B4 nir09) plus `MTL.json`: 65 files, 411,160,598 bytes.
  `sources.tsv` pins each file's size and Azure Content-MD5, and SHA-256
  receipts are written at download time.
- **Access:** Planetary Computer's anonymous read-only SAS (no account or
  key). It is fetched per run and never logged.
- **License:** public domain (USGS).
  - The MPC collection links the USGS data policy as rel=license, titled
    "Public Domain", with NASA and USGS as licensors.
  - The policy states: "Most of the satellite images supplied by U.S.
    Federal civil agencies are public domain (such as Landsat or ASTER). …
    All public domain imagery may be used, shared, transferred, or
    redistributed without restriction."
  - The USGS-managed AWS Open Data Registry entry "USGS Landsat" states:
    "There are no restrictions on Landsat data downloaded from the USGS; it
    can be used or redistributed as desired."
  - All three documents are captured, phrase-checked and SHA-256-pinned:
    MPC JSON 10,928 bytes; USGS policy 89,600 bytes; registry 16,826 bytes.
- **Provenance:** every MTL credits "Image courtesy of the U.S. Geological
  Survey". This includes scenes received at international stations (KIS,
  FUI, RSA, ASA, PAC), which are USGS archive products.
- **Citation:** Landsat 1-5 MSS Collection 2 Level-1, USGS,
  doi:10.5066/P9AF14YV.

## Shape and conversion

Each natural record is one scene band: one Cloud-Optimized GeoTIFF.

The decoder reads only IFD 0:
- uint8, SampleFormat 1, Photometric 1;
- Deflate, Predictor 1, 256 × 256 tiles, GDAL_NODATA "0".

It inflates every tile with exact-length checks and crops edge-tile padding
to the per-scene shape. That shape (3381-4262 rows × 3761-4304 columns)
equals STAC `proj:shape` and MTL `REFLECTIVE_LINES/SAMPLES`. Output is
row-major (north to south, west to east) uint8. The decoder does no
rescaling, remapping, resampling or band combination, and ignores the six
overview IFDs and the uint16 QA assets.

Scene rule, per fixed WRS-2 path/row:
- Landsat-5, MSS, L1TP, Tier 1, collection 02;
- date 1984-03-01..1993-12-31;
- cloud < 5 and sun elevation > 30°;
- take the lowest cloud, then the highest sun, then the earliest date, then
  the id.

The 13 path/rows were chosen for biome spread from 1,826 qualifying scenes
on 384 path/rows, after dropping ocean- or cloud-dominated footprints:

| WRS-2 | Region | Date |
|---|---|---|
| 186/041 | Fezzan, Libya | 1984-05-21 |
| 176/052 | Kordofan, Sudan | 1985-03-31 |
| 170/042 | Harrat Khaybar, Saudi Arabia | 1988-08-04 |
| 162/029 | Aral Sea / Ustyurt | 1986-05-19 |
| 104/073 | Barkly-Tanami, Australia | 1991-10-18 |
| 230/077 | Gran Chaco, Argentina | 1984-09-30 |
| 225/080 | Corrientes / Iberá, Argentina | 1984-08-26 |
| 030/037 | Llano Estacado, Texas | 1986-05-06 |
| 021/030 | Lower Michigan | 1986-06-08 |
| 015/042 | Everglades, Florida | 1986-04-27 |
| 065/011 | Mackenzie Delta, Canada | 1984-06-22 |
| 171/012 | Bolshezemelskaya tundra, Russia | 1985-07-02 |
| 039/017 | Canadian Shield, NWT | 1985-07-05 |

Build and verify both treat the following as fatal:
- size, MD5 or TIFF-structure mismatches;
- MTL semantics that are not Landsat-5 / MSS / L1TP / T1 / 02, or a wrong
  path/row, date, shape, UINT8 type or QCAL 1..255 range;
- per band: fewer than 1,000,000 valid pixels, fill outside 0.05..0.70,
  fewer than 16 distinct DN, saturation above 60% of valid pixels, or
  coherence above 0.6;
- per scene: band fill masks agreeing on less than 99% of pixels, or
  corr(B1,B2) or corr(B3,B4) below 0.5.

## Accepted output

| Metric | Value |
|---|---|
| Primary samples | 52 (13 scenes × 4 bands) |
| Values per sample | 12,976,278-18,343,648 (median 13,814,153) |
| Primary values / bytes | 746,545,896 |
| Fill (DN 0) | 250,531,730 (0.336); per band 0.261-0.449 |
| Valid DN span | 1..255 (MTL QCAL 1..255) |
| Distinct valid DN per band | 83-255 (median 254.5) |
| Shannon entropy incl. fill | 3.67-6.17 bits (median 4.99) |
| Saturation (DN 255) | Fezzan B2 42.8%, B3 40.0%; Mackenzie B1-B2 3.9-4.6%; all others ≤ 1.3% |
| Coherence (mean neighbour diff / std) | 0.046-0.288 |
| Band-mask agreement | ≥ 0.9986 |
| corr(B1,B2) / corr(B3,B4) | 0.796-0.996 / 0.833-0.998 |
| Radiance scale per band (constant across scenes) | B1 0.88504, B2 0.66024, B3 0.55866 or 0.60551, B4 0.46654 |

Aggregate decoded SHA-256 (samples concatenated in index order):
`c62c88d1977d625bd5f36530459296dbcf2c5c9912895710028ce978f39ef036`

## Judge checks

- **Gate:** `gate.py staging/mpc_landsat_c2_l1_mss_dn_u8` passes with no
  warnings (52 samples, median 13,814,153 values, width 8).
- **Verify:** I ran `verify.sh` myself (exit 0, about 3 min). All 52
  samples were re-derived "identical" by the separate decoder, and the 3
  rights documents re-checked offline. Statistics, scene guards and totals
  matched.
- **Build is local-only:** `build.sh` and `verify.sh` contain no network
  calls, and both refuse to run if the plan differs from `sources.tsv`.
- **Download provenance:** the first download run (00:42) failed on MTL
  ORIGIN whitespace in 3 files, and `mtl_check.py` was fixed at 00:49. The
  passing run (00:51-00:53) postdates every download-path script edit. The
  driver rebuilt at 01:11, after the last `build.sh`/`verify.sh` edits at
  01:01.
- **Bytes:** I parsed IFD 0 with my own minimal reader and inflated 7 tiles
  (including the last edge tile) from each of 8 random COGs. All matched the
  samples byte for byte.
  - Downsampled renders of 6 bands and full-resolution crops across a tile
    corner show real north-up scenes with no seams: Saginaw Bay at upper
    right, sea ice north of the Mackenzie Delta, field mosaics in Michigan.
    The smoke plume and cumulus at 039/017 and the blown-out Fezzan erg
    match the disclosures.
  - Histograms show the MSS quantization ripple without empty bins.
  - Band pairs are not near-duplicates (at most 8.5% equal pixels, mean
    |diff| 6.7-41 DN).
  - The footprint interior gives zlib-6 0.52-0.64.
- **Homogeneity:** I read the per-band radiance coefficients for all 13
  scenes; each band has one scale (B3 has two date-dependent CPF variants).
- **License:** I phrase-checked all three captured documents and re-fetched
  the USGS-managed registry YAML live ("There are no restrictions on Landsat
  data downloaded from the USGS"); usgs.gov returned 403 to my curl.
- **Novelty:** `novelty.py` found no URL or DOI matches. The term matches
  were only the Statlog MSS table, scene cloud-cover metadata and the
  `needs_tooling` OLI 16-bit draft. No 8-bit optical radiance scene family
  exists downstream.
- **Secrets:** no SAS signature, key or token appears in any recipe file or
  log.
- **Minor note:** the manifest says "five continents", but 171/012 lies in
  European Russia, so there are six. The understatement does not affect the
  realized scope (13 scenes, 52 samples).
