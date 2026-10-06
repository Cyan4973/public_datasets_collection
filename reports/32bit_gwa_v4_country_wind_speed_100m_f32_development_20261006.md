# Global Wind Atlas 4.0 country wind-speed-at-100-m float32 development

## Outcome

Accepted `gwa_v4_country_wind_speed_100m_f32`. It holds 31 complete Global Wind Atlas 4.0 country rasters of modelled long-term mean wind speed at 100 m above ground, decoded to native little-endian float32.

This is a new quantity for the corpus. Local wind material is point or station time series (`nasa_power_daily_wind`, `noaa_isd_lite`, `open_meteo_hourly_wind`, NDBC, GHCN AWND) or instantaneous 0.25° ERA5 pressure-level wind components (`weatherbench2_era5_pressure_level_fields_f32`). GWA is a terrain-downscaled, 250 m, long-term mean scalar speed climatology from a new source (DTU).

It is a modelled climatology, not measurement. ERA5 2008-2017 forcing feeds WRF at 3 km, and the result is downscaled with PyWAsP to a predicted wind climate every 0.0025°.

## Source and rights

- Source: GWA 4.0 country GIS files, `https://gwa.cdn.nazkamapps.com/country_tifs_v4/{ISO3}_wind-speed_100m.tif`. This is the redirect target of the documented API `https://globalwindatlas.info/api/gis/country/{ISO3}/wind-speed/100`.
- Pins: `countries.tsv` holds per-file size, single-part S3 ETag (= MD5), sha256, Last-Modified (2025-06-11..13), IFD0 geometry and tiepoint. `download.sh`, `build.sh` and `verify.sh` all enforce them.
- License: CC BY 4.0. The GWA Terms of Use (served in `mapframe.bundle.js`) define "the Works" as the content the GWA App provides and state: "The Works are licensed under the Creative Commons Attribution 4.0 International license, CC BY 4.0, except where expressly stated that another license applies." No other license is stated for the GIS layers.
- Access conditions:
  - The GIS page says "The provided URL can also be used as an API service" and "This API service is not to be used for bulk downloads of all countries or datasets."
  - The ToS also forbid robots accessing "the GWA App".
  - The recipe fetches a fixed list of 31 of about 250 countries, 1 of 12 layers and 1 of 5 heights, once, sequentially with pauses, from the static CDN object. The judge reads this as within the API offer and not a bulk download. The README discloses the judgment.
- Attribution: the requested DTU/World Bank/Vortex/ESMAP text and the Davis et al. BAMS 2023 citation are in the README and manifest.

## Shape and conversion

- Natural record: one complete full-resolution IFD0 country raster `[H, W]`, row-major (north row first, west column first). Overview IFDs are skipped.
- Decode (`scripts/gwa_tiff.py`, stdlib plus the `zstd` CLI), in order:
  1. Parse the BigTIFF IFD chain.
  2. Require float32, ZSTD (50000), predictor 3, 512×512 tiles, GDAL_NODATA nan, EPSG:4326 and 0.0025° pixels.
  3. Zstd-decode each tile, which must be exactly 1 MiB.
  4. Undo the libtiff floating-point predictor per row.
  5. Write little-endian float32 and crop the edge tiles.
- No resampling, masking, remapping or unit change.
- Missing values: source NaN (`0x7fc00000`) outside the country + EEZ mask is preserved in place. Build and verify both require:
  - a single NaN bit pattern;
  - a per-country valid share within 0.30-0.90;
  - finite valid values within 0-40 m/s;
  - at least 10,000 distinct valid values and a valid span of at least 0.5 m/s.
  - Verify also requires a dataset-wide valid share within 0.45-0.75.
- Selection (`discover.sh`): from a hand-picked pool of small and medium countries, a country qualified with HEAD 200, a single-part ETag, at most 17 MB and a smallest-overview valid share of at least 0.45. 43 qualified, 31 were pinned for regional spread, and the 12 left out are named. Erratum: the docs call the pool 77 countries, but `discover.sh` lists 76. This does not affect realized scope.

## Accepted output

- Samples: 31 (NLD EST LVA LTU CZE HUN CHE SVN SRB BGR LBN CYP KWT QAT ARE GEO AZE SWZ LSO RWA UGA DJI SEN GMB BTN BGD KHM SLV PAN BLZ JAM)
- Primary values: 95,611,417
- Primary bytes: 382,445,668
- Download bytes: 176,707,851 (31 BigTIFFs)
- Valid values: 55,783,476
- NaN values: 39,827,941 (41.66%), dataset valid share 0.5834
- Per-country valid share: 0.520 (KHM) to 0.736 (SWZ)
- Smallest sample: SWZ, 364,635 values (1,458,540 bytes)
- Median sample: 2,908,444 values (CYP)
- Largest sample: PAN, 8,821,708 values (35,286,832 bytes)
- Valid range: 0.066 m/s (BTN) to 21.620 m/s (GEO)
- Per-country medians: 2.02 m/s (BTN) to 9.47 m/s (NLD)
- Distinct valid bit patterns per country: 262,708 (SWZ) to 4,116,520 (PAN)

## Judge checks

- `gate.py` PASS. Its single warning, "57% of scanned values are NaN", comes from head-weighted chunk sampling. On NLD, KWT, CHE, BGD, JAM and QAT the head NaN share is 0.58-0.93, the middle 0.09-0.25 and the full raster 0.37-0.46. The real full-dataset figure is 41.66%.
- Ran `verify.sh` myself: PASS in 51 s. All 31 sources match their size, MD5 and sha256 pins, and all 31 samples are byte-identical to verify's independent re-decode. `build.sh`, `verify.sh` and `gwa_tiff.py` contain no network calls. The driver's download re-run was 31/31 sha256-validated cache hits, and `build.latest.log` shows the synthetic self-test passing.
- Wrote a third decoder in `/tmp` for the source IFD1 overviews of SWZ, LBN, BTN and GMB and compared it with 2×2 means of the emitted samples. Median absolute difference was 0.0011-0.107 m/s and mask agreement 97.2-98.6%; random pixel pairs typically differ by about 1 m/s. This confirms predictor decode, tile placement and byte order.
- Byte plausibility:
  - Only NaN pattern `0x7fc00000`; no negative values.
  - NLD climbs from about 7.1 m/s inland to about 10.0 m/s over the North Sea. CHE has an Alpine tail to 19.9 m/s. KWT and QAT stay in narrow desert ranges.
  - Mantissa trailing zeros are geometric, so the full float32 precision is used.
  - Only about 0.01% of adjacent pixels are bit-identical, so the grid is not upsampled.
- Cross-sample duplication: 10 adjacent country pairs share bit-identical buffered-border pixels, 295,887 of 55,783,476 valid values (0.53%). The worst case is GMB inside SEN's box, at 17.9% of GMB's valid pixels. The source publishes per-country clips this way, and the effect is negligible at dataset level.
- Rights: fetched `mapframe.bundle.js` and confirmed verbatim the CC BY 4.0 grant over "the Works", the GIS page's API offer and bulk-download restriction, and the ToS robot clause. There are no credentials and no personal data.
- Novelty: `novelty.py` on both resource URLs with wind-atlas terms found no URL, registry or downstream match. No accepted 32-bit geo-raster family appears in `pipeline/candidates.tsv`.
