# FMI Korpo 0.5° PPI Doppler radial velocity uint8 development

## Outcome

Accepted `fmi_radar_ppi_vrad_u8`. It holds 75 native uint8 Doppler radial-velocity rasters from the lowest (0.5°) quality-controlled PPI of the Finnish Meteorological Institute's Korpo (`fikor`) C-band radar.

This is the corpus's first Doppler velocity family and its first FMI source. The nearest local families are `noaa_nexrad_level3_nids_radials_u8` (N0Q base *reflectivity* only), `sevir_vil_storm_events_u8` (vertically integrated liquid mosaics) and `dwd_radolan_rw_precip_i16` (composite precipitation). None carries radial velocity, and the downstream corpus has no radial-velocity family either.

## Source and rights

- Source: FMI public AWS Open Data bucket `fmi-opendata-radar-geotiff` (eu-west-1), anonymous HTTPS, not requester-pays.
- Objects: 75 keys `<YYYY>/<MM>/<DD>/fikor/<YYYYMMDDHH>00_fikor_ppi_0.5_vrad_qc.tif`, each pinned in `sources.tsv` by S3 versionId, size and single-part ETag MD5.
- Download: 31,677,353 bytes (201–696 KB per file).
- License: CC BY 4.0. FMI's "Radar data on AWS S3" page says: "The data is licensed by the Creative Commons Attribution 4.0 International license (CC BY 4.0)", with the GeoTIFF bucket named directly after it. The AWS open-data-registry `datasets/fmi-radar.yaml` lists `License: Creative Commons Attribution 4.0 International (CC BY 4.0)` for `arn:aws:s3:::fmi-opendata-radar-geotiff`. Attribute FMI.

## Shape and conversion

- Natural record: one PPI scan product file, i.e. one 2003 × 2003 band-1 raster with 250 m pixels on EPSG:3067 (TM35FIN), a 500 km square centred on the radar.
- Codes:
  - 112..143 are velocity `v = 0.5·code − 64` m/s, from −8.0 to +7.5 m/s. Velocities are folded into the single-PRF Nyquist interval and not dealiased.
  - 0 is no echo inside coverage (inferred ODIM *undetect*).
  - 255 is the declared GDAL NoData, the corners outside the 250 km disc.
- Conversion: a pure-stdlib classic-TIFF IFD parse and TIFF-LZW decode (MSB-first, Clear 256 / EOI 257, early change, 9–12 bit) of 16 tiles of 512 × 512, placed row-major and cropped to 2003 × 2003. Codes are written unchanged. There is no predictor, remap or dealiasing.
- Per-file assertions:
  - GDAL SCALE 0.5 / OFFSET −64 / UNITS VRADH / IMAGETYPE
  - NoData '255'
  - Software `Rack_fmi.fi 10.7`
  - description `COMP:VRADH:PPI:elangles(0.5)`
  - DateTime equal to the key timestamp
  - pinned pixel scale and tiepoint, EPSG:3067
  - every code in {0, 112..143, 255}
  - NoData fraction 0.20–0.30, velocity fraction ≥ 0.05, at least 16 distinct velocity codes
  - no duplicate raster
- Homogeneity: one site, one elevation, one quantity, QC flavour, code lattice and grid, and one processing-software version. Excluded:
  - the Rack 8.3.2 (≤ 2025-02), sporadic 14.0.1 and 16.4 (from 2026-03-24) eras
  - the 2026-09 `finrad` rename
  - the 0.7° and 1.5° VRAD products
- Selection (`discover.sh`, metadata only): HEAD every 00/06/12/18 UTC scan from 2025-03-01 to 2026-03-31 (1,554 exist) and keep the largest file per day. Then, per month, take the six largest of at least 200,000 bytes that pass the header check, never on the same or an adjacent day as an already chosen scan.

## Accepted output

- Primary samples: 75
- Primary values / bytes: 300,900,675
- Sample size: 4,012,009 values each (min = median = max)
- Months covered: 13 (2025-03..2026-03), six scans per month, three in 2026-02
- Hours: 00 UTC ×26, 06 ×20, 12 ×15, 18 ×14
- Pixel classes over all samples: velocity 32.7%, undetect (0) 45.7%, NoData (255) 21.6%
- NoData: exactly 865,338 pixels per scan
- Velocity fraction per scan: 11.7%–60.8%, median 31.6%
- Velocity codes: all 32 occur in every scan; entropy 4.95 of 5 bits
- Aggregate SHA-256 of per-sample SHA-256s: `f486e9c9651c77367460e6e5d37792b5525ccb0735dae3eb36fc220de7ed3dc3`

Caveats (documented in the README): only 34 of 256 codes occur, so the velocity payload carries about 5 bits within native 8-bit storage. Sentinels cover 39–88% of each raster. The product is FMI's operational Cartesian resampling of polar gates. Selecting by size biases toward echo-rich weather.

## Judge checks

- `python3 tools/autocollect/gate.py staging/fmi_radar_ppi_vrad_u8`: PASS, no warnings.
- `bash staging/fmi_radar_ppi_vrad_u8/verify.sh`, run by me: selftest_ok, then verify_ok for 75 samples, 300,900,675 bytes, 13 months. Every sample was re-decoded from its source and compared byte-for-byte.
- build.sh and verify.sh read only `.data/` files; grep found no network calls and no credentials in any script or `sources.tsv`.
- Driver download log: 75/75 files, 31,677,353 bytes, each passing the size, MD5 and full product check. Build log aggregate equals the claimed SHA-256.
- Independent decode: my own IFD parser and differently structured TIFF-LZW decoder reproduced samples 202503050000, 202602110600, 202510301800, 202601080600 and 202507310000 exactly. TIFF tags match the claims.
- Byte inspection with stdlib Python over all 75 samples:
  - Every code is in {0, 112..143, 255}.
  - The NoData mask is identical in every scan: a disc centred at pixel (1001.0, 1001.3) with radius 250.2 km. Code 0 never occurs outside it.
  - Mean folded difference between horizontally adjacent velocity pixels is 0.30–2.39 codes, against about 8 for noise, so the fields are smooth.
  - ASCII thumbnails show velocity ramps with ±Nyquist fold lines.
  - Same-pixel agreement with the previous scan is 1.2–6.5%, chance level for 32 codes, so there are no near-duplicates.
- Rights: I fetched the FMI page and the registry YAML myself and confirmed the CC BY 4.0 statements cover this bucket.
- Novelty: `novelty.py` with the bucket and registry URLs and the terms fmi, radial velocity, vrad, doppler, fikor, radar and nyquist found no FMI or radial-velocity family in `datasets/`, the registry, the ledger or downstream. The NEXRAD L3 manifest is N0Q-only. `noaa_nexrad_level2_moments_i16` is blocked and at a different width. Only one 8-bit weather-radar family (SEVIR VIL) has been accepted in this effort, so the breadth limit does not apply.
