# Global Wind Atlas v4 Country Rasters: Mean Wind Speed at 100 m (0.0025 deg grid) GeoTIFF Float32

- Candidate id: `gwa_v4_country_wind_speed_100m_f32`
- Width: float32
- Quantity: Long-term mean wind speed (m/s) at 100 m above ground from the DTU/World Bank Global Wind Atlas v4 microscale downscaling (WAsP on reanalysis), on a 0.0025-degree (about 250 m) grid, one raster per country, with NaN outside the country mask.
- Source: https://globalwindatlas.info/
- Resources: https://globalwindatlas.info/api/gis/country/DNK/wind-speed/100, https://gwa.cdn.nazkamapps.com/country_tifs_v4/DNK_wind-speed_100m.tif, https://gwa.cdn.nazkamapps.com/country_tifs_v4/CHE_wind-speed_100m.tif, https://gwa.cdn.nazkamapps.com/country_tifs_v4/JOR_wind-speed_100m.tif
- License: CC-BY-4.0
- License evidence: https://globalwindatlas.info/en/about/TermsOfUse
- License quote: "You are encouraged to use the GWA App and the Works to benefit yourself and others in creative ways. The Works are licensed under the Creative Commons Attribution 4.0 International license, CC BY 4.0, except where expressly stated that another license applies." (Terms of Use text served in https://globalwindatlas.info/mapframe.bundle.js)
- Natural record: One country raster: the full-resolution IFD0 of {ISO3}_wind-speed_100m.tif (e.g. DNK 5321 x 1576). Reduced-resolution overview IFDs are skipped. NaN = GDAL_NODATA outside the country.
- Estimated samples: 20
- Estimated primary values: 95,000,000
- Estimated download bytes: 115,000,000
- Estimated primary bytes: 380,000,000
- Decode path: BigTIFF (magic 43) IFD parse with struct: 512x512 tiles, BitsPerSample 32, SampleFormat 3, Compression 50000 (ZSTD), Predictor 3. Per tile: range bytes, `zstd -d` CLI (present at /usr/bin/zstd, MPC precedent). Undo the floating-point predictor: per row, itertools.accumulate byte deltas mod 256, then de-interleave 4 big-endian byte planes. Repack as float32 LE and crop edge tiles to width/height.
- Novelty kind: new_quantity
- Novelty evidence: novelty.py --url .../DNK_wind-speed_100m.tif --terms 'wind atlas' 'wind speed' globalwindatlas dtu: no URL or registry or ledger match. 'Wind speed' hits are only point or station time series (open_meteo_wind_f32 hourly, nasa_power_daily_wind f64, NDBC, GHCN, ISD, bike/appliance tables). No wind-resource or energy-resource rasters exist at any width; the closest raster modality is worldclim_tavg_10m (temperature climatology).
- Homogeneity: One layer (wind-speed at 100 m), one model release (country_tifs_v4), identical grid spacing, CRS (WGS84) and units across countries. Don't mix power-density, capacity-factor or other heights. Choose about 20 small/medium countries (e.g. LBN, SVN, ARM, ISR, BEL, CHE, SVK, SLV, JOR, SRB, LTU, NLD, CZE, GEO, HUN, EST, AUT, HRV, LVA, BGR) to stay well under 1 GB.
- Risks: Modelled climatology, not measurement. NaN padding outside country masks inflates bytes (one DNK tile was 67% NaN); report the valid-pixel share. The CDN path is versioned (v4) without checksums, so pin sizes and sha256. Large countries are huge (RUS 2.18 GB, CAN 1.29 GB) and must be excluded. TWN gave no size. The license is rendered by a JS SPA (quote taken from the app bundle). Predictor-3 decode in pure Python is slowish (about 1-2 min per 100 MB).
- Probe evidence: API https://globalwindatlas.info/api/gis/country/DNK/wind-speed/100 gives 302 to the CDN TIFF (HTTP 200, image/tiff, 9,702,704 B, accept-ranges). HEAD sizes for 67 countries: LBN 1.5 MB ... DEU 30.6 MB ... RUS 2.18 GB. BigTIFF header range-read: IFD0 5321x1576, 44 tiles, ZSTD 50000, predictor 3, SampleFormat 3, PixelScale 0.0025. Fetched one 154,517 B tile: zstd decoded to 1,048,576 B, predictor undone, 87,590 valid px with range 9.986-10.452 m/s (offshore Denmark), rest NaN.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_32bit/scout.20261005_234311.jsonl`).
