# Blocked: usgs_sidescan_sonar_tiff_u16

- Date: 2026-07-22
- Candidate: `staging/usgs_sidescan_sonar_tiff_u16`
- Domain: marine sidescan sonar backscatter, underwater acoustic imagery
- Intended natural sample: one GLORIA sidescan mosaic TIFF uncompressed uint16
- Intended primary: `sidescan_sonar_mosaic_u16` uint16 raster

## Attempt

User ran `bash staging/usgs_sidescan_sonar_tiff_u16/download.sh` on 2026-07-22.

Log: `.data/logs/usgs_sidescan_sonar_tiff_u16/download.latest.log`

```
warning: seed fetch failed: https://catalog.data.gov/dataset/gmx-q16-tif-u-s-gulf-of-mexico-eez-gloria-sidescan-sonar-data-mosaic-16-of-16-acea-50-m-cl: HTTP Error 404: Not Found
no candidate URLs discovered; provide URL list or adjust seed selectors
```

## Reason

The data.gov dataset slug `gmx-q16-tif-u-s-gulf-of-mexico-eez-gloria-sidescan-sonar-data-mosaic-16-of-16-acea-50-m-cl` is no longer valid (HTTP 404). The catalog entry was likely retired or renamed during data.gov migration. No fallback TIFF URLs were discovered from the single seed.

## Evidence

- Log path: `.data/logs/usgs_sidescan_sonar_tiff_u16/download.latest.log`
- Seed URL: `https://catalog.data.gov/dataset/gmx-q16-tif-u-s-gulf-of-mexico-eez-gloria-sidescan-sonar-data-mosaic-16-of-16-acea-50-m-cl`
- Result: 0 files downloaded, bounded_url_download exits with "no candidate URLs discovered"

## Classification

**blocked** — source not reachable via current seed.

## Retry Condition

Retry only after identifying a stable direct source for uncompressed uint16 GLORIA sidescan TIFF mosaics:

- Use USGS CMGDS ScienceBase items, e.g. `https://www.sciencebase.gov/catalog/item/{id}` with direct TIFF links, or
- Use USGS Coastal and Marine Data Portal with data-release DOI that lists direct `*.tif` downloads, or
- Provide exact direct TIFF URLs via `USGS_SIDESCAN_URLS_FILE`.

The build path (`tools/numeric16_extract.py --format tiff`) is sound and already rejects compressed/RGB/8-bit TIFFs.

## Value if Fixed

Would add underwater acoustic imagery domain (seafloor sidescan backscatter), distinct from spaceborne SAR (`sentinel1_grd_measurement_u16`) and depth camera (`tum_rgbd_depth_u16`).

