# Terra ASTER L1T thermal-infrared radiance DN uint16 development

## Outcome

Accepted `mpc_aster_l1t_tir_u16` after one repair cycle. The repair concerned rights evidence only; bytes, decoders and the scene plan were unchanged.

This is the first ASTER family in the corpus. It is a new source and instrument: polar-orbiting, five-band, 90 m thermal-infrared radiance over land. The nearest accepted family, `mpc_goes18_abi_cmi_c13_fulldisk_u16`, is also 12-bit thermal-IR codes in uint16. It is a different material: one band, a geostationary 2 km full disk, and brightness-temperature codes dominated by cloud and ocean.

## Source and rights

- Source: Microsoft Planetary Computer STAC collection `aster-l1t`, asset `TIR` (Cloud-Optimized GeoTIFF). The product is NASA/METI AST_L1T v003 from LP DAAC (doi:10.5067/ASTER/AST_L1T.003).
- Access: anonymous, short-lived, read-only Planetary Computer SAS. No account, key or login, and the token is never logged.
- Pinned scope: 51 STAC items in `sources.tsv`, with item id, href, exact size and Azure Content-MD5 for every file. Total download is 157,104,582 bytes.
- License: public domain (`LicenseRef-Public-Domain`).
  - The grant is the USGS data policy, which the Planetary Computer collection links under the license title "Public Domain". The link https://www.usgs.gov/core-science-systems/hdds/data-policy redirects (HTTP 200) to https://www.usgs.gov/emergency-operations-portal/data-policy.
  - Its "Public Imagery" section reads: "Most of the satellite images supplied by U.S. Federal civil agencies are public domain (such as Landsat or ASTER). ... All public domain imagery may be used, shared, transferred, or redistributed without restriction. However, there should be acknowledgement of the image source within any derived maps, products, or publications."
  - `download.sh` captures the page before any raster transfer: 89,600 bytes, sha256 `b91a7cda9f802beaf49b3b7bf3426b3f4dad71435c374bf66424d786cce6712e`. It phrase-checks the page and records it in `rights_receipts.tsv`; `build.sh` refuses to run without `check=ok`, and `verify.sh` re-checks it offline.
  - The MPC collection JSON is also captured: 9,925 bytes, sha256 `65f1fe15ee8394f1b9f8d49f3158f2f99e765c69a713648ce7b548de7fcca8e2`. It names NASA and USGS as licensors. Its STAC `license` field reads `proprietary` and serves only as a pointer to the policy link.
  - Supporting: the NASA Earthdata notice that LP DAAC has distributed AST_L1T at no charge since 2016-04-01.
  - Not claimed: Earthdata CC0, which covers only NASA-led missions. ASTER is a METI instrument.
  - Attribution: NASA/METI/AIST/Japan Spacesystems and the U.S./Japan ASTER Science Team.

## Shape and conversion

- Natural record: one complete AST_L1T scene's TIR raster, `height × width × 5` (807-956 rows by 918-1030 columns). No tiling or sharding.
- Scene rule: 26 fixed regions (deserts, high and cold terrain, steppe and savanna, farmland) × 2 seasonal windows (Feb 15 - Apr 30, Jul 1 - Sep 15).
  - A scene qualifies with a TIR asset, `0 <= eo:cloud_cover < 10` and `view:sun_elevation > 20` (daytime only).
  - Among qualifying scenes it takes the lowest cloud cover, then the earliest datetime, then the item id, starting from a base year with fallback across 2000-2006.
  - 51 of 52 slots resolved; Patagonia Jul-Sep has no qualifying scene in any year.
- Decode: pure-stdlib TIFF parsing of the primary IFD (LE, 5 × uint16 chunky, Deflate, Predictor 2, 512² tiles).
  - Each tile is inflated, then Predictor 2 is undone with a 5-sample stride modulo 2^16, and edge tiles are cropped.
  - Output is little-endian uint16 in source pixel-interleaved order: rows north to south, columns west to east, band 10 first.
- Representation: `native_numeric`. There is no scaling, radiance or temperature conversion, reprojection or remap. Unit-conversion coefficients are recorded in the index but not applied.
- Missing values: source-native fill 0 outside the rotated swath is kept in place; valid DN are 1..4095. Shared build/verify guards:
  - fill fraction 0.05-0.80;
  - at least 50,000 valid pixels and 64 distinct DN per band;
  - band fill masks agree on at least 98% of pixels;
  - corr(b13, b14) >= 0.5 and band-13 neighbour-difference/std <= 0.75.

## Accepted output

- Samples: 51 scenes from 26 regions; 26 are Feb-Apr and 25 Jul-Sep.
- Years: 2000: 4, 2001: 12, 2002: 11, 2003: 6, 2004: 10, 2005: 5, 2006: 3.
- Primary values: 202,936,125 uint16. Primary bytes: 405,872,250.
- Sample size: minimum 3,704,130 values, median 3,902,080, maximum 4,923,400 (7,408,260-9,846,800 bytes).
- Fill: 77,267,407 values (38.1%); per-scene fill fraction 0.332-0.502.
- Valid DN: 370-3283. Distinct DN per band per scene: 183-1634 (median 623).
- Decode guards: corr(b13, b14) 0.964-1.000; band-13 coherence 0.077-0.330; mask agreement at least 99.78%.
- Aggregate digest (sha256 of the concatenated per-sample sha256 values, sorted by sample path): `314f997336b331fe4c3ba2e4fdebae1dc466797cd4887cbdd5a2f9c8e4dcb26d`.

## Judge checks

- `python3 tools/autocollect/gate.py staging/mpc_aster_l1t_tir_u16`: PASS, no warnings.
- `bash staging/mpc_aster_l1t_tir_u16/verify.sh` run by the judge: exit 0 in 72 s.
  - All 51 samples were re-derived byte-identically by the independent decoder.
  - The rights checks passed offline against the receipts.
- `build.sh` and `verify.sh` contain no network calls.
- `sources.tsv` is byte-identical to the driver's `discovered_sources.tsv`.
- The driver download of 2026-10-05 19:28 captured the rights pages and cache-hit all 51 COGs with MD5 re-validated.
- The current `rights_check.py usgs|mpc|earthdata` exits 0 on the saved files.
- No real SAS signature appears in any log.
- Judge-written `struct`/`zlib` decode of one random tile from each of 6 random COGs: exact match.
- Planck brightness temperature from handbook UCC is physical:
  - Rub al Khali August band 13: 319.7 K. Bands 10-12 are about 15 K lower, the quartz reststrahlen dip, which confirms band order.
  - Lut July: 323.6 K.
  - Greenland April: 257.9 K.
  - Yakutia April: 273.3 K.
- A band-13 quicklook mosaic (Karakoram, Rub al Khali, Greenland, Kalahari, Kansas, Yakutia) shows real terrain and rotated swaths with no decode artifacts.
- README outlier claims match the bytes: the five Kalahari Jul-Sep single-band spikes and the Atacama Feb-Apr multi-band hot spot.
- Rights: the judge read the captured USGS page text (ASTER named as public domain, redistribution without restriction, attribution requested) and the MPC JSON license link and licensors.
- Novelty: `novelty.py` was run for the MPC collection URL, the astersa blob path and the DOI. Matches were only the shared MPC host and substring noise ("raster", "asterisk"); there is no ASTER family locally or downstream.
- Minor documentation nit, not blocking: the README gives zlib-6 spot ratios of 0.28-0.46, but the Karakoram Feb-Apr scene measures 0.473.
