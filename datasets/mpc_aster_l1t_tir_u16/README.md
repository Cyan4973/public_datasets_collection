# Terra ASTER L1T thermal-infrared radiance DN (uint16)

This recipe collects complete Terra ASTER L1T v003 scenes, thermal-infrared
(TIR) subsystem only. Each sample is one scene's five TIR bands (ImageData10..14,
8.1–11.65 µm) as at-sensor radiance digital numbers. The DN are 12-bit values
stored as uint16, precision terrain-corrected and resampled to a 90 m north-up
UTM grid. The source is the Microsoft Planetary Computer `aster-l1t`
collection, asset `TIR`.

    radiance [W m-2 sr-1 um-1] = (DN - 1) * UCC[band]      (DN 1..4095)
    UCC = 0.006822, 0.006780, 0.006590, 0.005693, 0.005225 (bands 10..14)
    0 = fill outside the rotated swath

The coefficients come from the ASTER User Handbook. They are recorded in the
index as documentation and are **not applied**.

## Scope and scene rule

- **Natural record:** one AST_L1T scene's TIR raster. Realized shapes run
  from 807 to 956 rows and 918 to 1030 columns, × 5 bands. The size varies with
  footprint and latitude, so each index row records
  `sample_shape = [height, width, 5]`. Samples are whole scenes; they are not
  tiled or sharded.
- **Regions:** 26 fixed bounding boxes chosen for climatic and terrain spread
  (listed in `discover.sh`):
  - deserts: Hoggar, Rub al Khali, Lut, Thar, Namib, Great Sandy,
    Death Valley, Chihuahua, Atacama, Taklamakan
  - cold and high terrain: Karakoram, Altiplano, Greenland ice margin, Yakutia
    taiga, Gobi, Patagonia
  - steppe and savanna: Sahel, Turkana, Kalahari, Aral, Anatolia, Cerrado
  - farmland: Loess Plateau, Iberian Meseta, Hungarian Plain, Kansas
- **Windows:** two seasonal windows per region, Feb 15 – Apr 30 and Jul 1 –
  Sep 15, for at most 52 scenes.
- **Selection:** each region has a base year (2000..2006, rotated across
  regions). If no scene qualifies, discovery falls back to the nearest other
  year in 2000–2006, which is the whole Planetary Computer ASTER archive. A
  scene qualifies when:
  - it has a `TIR` asset;
  - `0 <= eo:cloud_cover < 10` (also requested server-side);
  - `view:sun_elevation > 20`, so it is daytime only, one acquisition regime;
  - it was not already chosen.

  Among qualifying scenes it takes the lowest cloud cover, then the earliest
  datetime, then the item id.
- **Excluded:** VNIR/SWIR assets (uint8, a different family), night scenes,
  overview IFDs, and the QA/browse assets.

## Realized output (build of 2026-10-05)

- **Coverage:** 51 scenes from 26 regions; 26 are Feb–Apr and 25 are Jul–Sep.
  Patagonia Jul–Sep had no qualifying scene in any year (low winter sun or
  cloud).
- **Years:** 2000: 4, 2001: 12, 2002: 11, 2003: 6, 2004: 10, 2005: 5, 2006: 3.
- **Acquisition conditions:** sun elevation 28.0–72.5°, cloud cover 0–8%.
- **Volume:** 405,872,250 bytes in total, which is 202,936,125 uint16 values.
  Each sample is 7.4–9.8 MB; the median sample holds 3,902,080 values.
- **Downloads:** 51 COGs, 157,104,582 bytes. Content-MD5 is published and
  pinned for every file.
- **Values:** valid DN span 370–3283 overall, well inside 12 bits. Distinct
  valid DN per band and scene range from 183 to 1634 (median 623). The lowest
  counts come from uniform targets: Rub al Khali sand, Yakutia snow in April,
  and the Taklamakan in February. The highest come from mixed terrain:
  Karakoram, Hoggar in summer, and Chihuahua.
- **Fill:** fill fraction per scene is 0.332–0.502, highest for the
  high-latitude Greenland and Yakutia swaths.
- **Outlier pixels:** a few isolated single-band spikes are source detector
  artifacts and are kept as they are. For example, the Kalahari Jul–Sep scene
  has five such pixels, with the other bands normal at each:
  - band 13 = 791 and 1378 at rows 212–213, col 559;
  - band 13 = 3002 and 2755 at row 308, cols 479–480;
  - band 11 = 3283 at row 699, col 374.
- **Hot spots:** rare multi-band hot spots also occur and are kept as source
  values. For example, the Atacama Feb–Apr scene has one at rows 161–162,
  cols 757–758: bands 10–12 read 1768–2463 there, against about 1270–1840 in
  the surrounding pixels, and bands 13–14 are raised too.
- **Decode-correctness guards:**
  - band 13/14 correlation 0.964–1.000;
  - band-13 neighbour-difference/std 0.077–0.330;
  - band fill masks agree on ≥ 99.78% of pixels.
- **Compressibility:** spot checks give zlib-6 ratios of 0.28–0.46 and value
  entropy of 5.3–7.6 bits, including the zero fill.
- **Band order:** the COG band descriptions read `ImageData10 TIR_Swath` …
  `ImageData14 TIR_Swath`, and no GDAL_NODATA tag is set.

## Plan resolution and pinning

On 2026-10-05 the authoring agent session could not reach any host: the local
egress filter refused all outbound requests from agent sessions. The scene
list was therefore resolved on the autocollect driver's first `download.sh`
run, by `discover.sh`. That script makes only metadata requests: 101 STAC
searches, then an anonymous SAS and a HEAD per chosen blob for Content-Length
and Azure Content-MD5.

The resolved plan was then pinned as `sources.tsv`. It records item id,
region, window, year, datetime, cloud cover, sun elevation and azimuth, TIR
href, exact size and Content-MD5.

`download.sh` now uses only `sources.tsv`. It requires exactly 51 scenes and
157,104,582 bytes, then validates every COG:

- exact size and pinned Content-MD5;
- classic LE TIFF magic;
- the TIR structure: 5 × uint16 chunky, Deflate, ImageData10..14 in order;
- a full inflate of every primary tile.

build.sh and verify.sh refuse to run if the plan under `.data/` differs from
`sources.tsv`.

`discover.sh` stays in the recipe as documentation. Re-running it is optional
and lets you compare a fresh resolution with the pin. The ASTER archive on
Planetary Computer is closed (2000-03-04 .. 2006-12-31).

## Decode

Pure standard-library Python, in `scripts/aster_tir_cog.py`:

- Parse the primary IFD: BitsPerSample 16×5, SampleFormat 1, Compression 8,
  PlanarConfiguration 1 (chunky), Predictor 2, 512 × 512 tiles.
- Inflate each tile. Every tile must inflate to exactly `tw*th*5` uint16
  values; GDAL sparse tiles (offset 0, byte count 0) read as zero.
- Undo TIFF Predictor 2 per tile row. For chunky data, each sample is
  differenced against the **same band of the previous pixel**, so the inverse
  is a running sum over every 5th element, modulo 65536.
- Copy rows into the grid and crop the right and bottom edge-tile padding.

The output keeps the **source pixel-interleaved order**: rows north→south,
columns west→east, and five band values per pixel, band 10 first.

`aster_tir_cog.py selftest` checks both decoders on synthetic TIFFs written by
an independent encoder:

- chunky 5-band images with edge tiles, predictor 1 and 2, sparse tiles, and
  values that force mod-2^16 wraparound;
- a check that the classic stride-1 mistake does not reproduce the data;
- rejection of a wrong band order and of the wrong byte order.

download.sh and build.sh run the self-test first. verify.sh re-derives every
sample with `scripts/tir_independent_decode.py`, which shares no code with
the build decoder, and byte-compares the result.

## Missing values and degeneracy guards

Fill `0` outside the swath footprint is preserved in place. A north-up box
around a rotated 60 km swath typically leaves 25–50% fill. build.sh and
verify.sh enforce the same bounds:

- every value ≤ 4095;
- fill fraction within 0.05..0.80;
- per band, ≥ 50,000 valid pixels and ≥ 64 distinct DN, with max > min;
- band fill masks agree on ≥ 98% of pixels;
- decode-correctness guards: corr(band 13, band 14) ≥ 0.5, and band-13 mean
  absolute horizontal neighbour difference / std ≤ 0.75. A mis-decoded
  predictor produces noise that fails both.

## License

- **Grant:** the USGS data policy
  (https://www.usgs.gov/emergency-operations-portal/data-policy). The
  Planetary Computer collection links it as its license under the title
  "Public Domain". MPC's original link is
  https://www.usgs.gov/core-science-systems/hdds/data-policy. The page reads:
  "Most of the satellite images supplied by U.S. Federal civil agencies are
  public domain (such as Landsat or ASTER). … All public domain imagery may be
  used, shared, transferred, or redistributed without restriction. However,
  there should be acknowledgement of the image source within any derived maps,
  products, or publications." This is the "Public Imagery" section of the USGS
  Hazards Data Distribution System data policy, which MPC uses as the license
  reference for this collection.
- **Captured evidence:** `download.sh` saves the policy page at
  `downloads/mpc_aster_l1t_tir_u16/rights/usgs_data_policy.html`, before any
  raster is downloaded. It tries MPC's link first and the current location as
  a fallback. The script then:
  - phrase-checks the tag-stripped text with `scripts/rights_check.py`: the
    regex `public domain\s*\(\s*such as landsat or aster\s*\)` plus the
    phrase "redistributed without restriction";
  - logs the matched sentences;
  - pins the requested and effective URL, HTTP code, size and sha256 in
    `downloads/mpc_aster_l1t_tir_u16/rights_receipts.tsv`.
- **Capture of 2026-10-05:** MPC's link redirected (HTTP 200) to the
  emergency-operations-portal location. The page is 89,600 bytes, sha256
  `b91a7cda9f80…6712e`, and both phrases matched.
- **Collection JSON:** the raw MPC collection JSON is saved as
  `rights/mpc_collection_aster-l1t.json`. It is checked for the
  rel=license "Public Domain" usgs.gov data-policy link, NASA and USGS listed
  as licensors, and TIR `raster:bands` of 5 × uint16 with nodata 0. In the
  capture of 2026-10-05 (9,925 bytes, sha256 `65f1fe15ee83…ca8e2`) the
  providers are NASA (producer, licensor), USGS (processor, producer,
  licensor) and Microsoft (host).
- **Enforcement:** `build.sh` refuses to run without `check=ok` receipts and
  copies the receipt rows into `ingest_stats.json`. `verify.sh` re-runs the
  checks offline on the saved bytes.
- **Supporting (optional, non-fatal):** the NASA Earthdata notice "ASTER Data
  Available at No Charge"
  (https://www.earthdata.nasa.gov/news/aster-data-available-no-charge) is
  saved as `rights/earthdata_aster_no_charge.html` (captured 2026-10-05,
  sha256 `fd9903ef4c17…afd30`). It reads: "On April 1, 2016, NASA's Land
  Processes Distributed Active Archive Center (LP DAAC) began distributing
  Terra … ASTER Level 1 Precision Terrain Corrected Registered At-Sensor
  Radiance (AST_L1T) data products over the entire globe at no charge."
- **Not claimed:** the STAC `license` field says `proprietary` and only points
  to the USGS page. Earthdata's CC0 default is not claimed either: its Data
  Use Guidance applies CC0 only to NASA-led missions, and data from partner
  (non-NASA-led) missions follow the sponsor's terms. ASTER is a METI (Japan)
  instrument on NASA's Terra.

Attribution, as the USGS policy requests: acknowledge the image source.
Cite: NASA/METI/AIST/Japan Spacesystems and U.S./Japan ASTER Science Team,
ASTER L1T V003, NASA EOSDIS LP DAAC, https://doi.org/10.5067/ASTER/AST_L1T.003

## Novelty

This is a new source and instrument for the local corpus: high-resolution,
polar-orbiting, multispectral thermal-infrared radiance over land. The
nearest existing family is `mpc_goes18_abi_cmi_c13_fulldisk_u16`, which is
also thermal IR stored as 12-bit codes in uint16. That family is a different
material: one band, a geostationary 2 km full disk, and brightness-temperature
codes dominated by cloud and ocean. This recipe has five interleaved TIR bands
at 90 m, land-surface detail, and radiance DN.

Other 16-bit EO families cover different quantities:

- Sentinel-2 L2A optical reflectance;
- Sentinel-1 SAR;
- terrain and soil rasters.

The only other local thermal-IR raster, `nasa_pds_themis_ir_mosaic_u8`, is
8-bit imagery of Mars. novelty.py finds no ASTER recipe, registry row, or
downstream family; its term hits are "raster"/"asterisk" substring noise.

## Run

```bash
bash staging/mpc_aster_l1t_tir_u16/download.sh   # 51 pinned COGs, 157,104,582 bytes, resumable
bash staging/mpc_aster_l1t_tir_u16/build.sh
bash staging/mpc_aster_l1t_tir_u16/verify.sh
```

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/mpc_aster_l1t_tir_u16/`.
