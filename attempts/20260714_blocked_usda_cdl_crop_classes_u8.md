# usda_cdl_crop_classes_u8

- Date: 2026-07-14
- Status: blocked before dataset acquisition
- Candidate dataset: USDA NASS Cropland Data Layer crop-class rasters
- Source: CropScape CDL service, `https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile`
- Why it looked promising: native byte-valued agricultural crop/land-use class rasters with materially different categorical structure from existing land-cover and segmentation datasets.
- Failure class: upstream_service_unavailable

## What Happened

The default bounded download attempted to resolve CDL ZIP URLs for:

- `cdl_2023_fips_10`
- `cdl_2023_fips_44`
- `cdl_2023_fips_09`
- `cdl_2023_fips_34`
- `cdl_2023_fips_24`
- `cdl_2023_fips_25`

The CropScape service first returned HTTP 502 for the first resolver request, then a later retry timed out for all default FIPS/year resolver requests. No ZIP URLs were resolved and no CDL raster payloads were downloaded.

The structured failure log is under:

- `.data/downloads/usda_cdl_crop_classes_u8/download_failures.tsv`

## Decision

Do not spend more runs on the service resolver right now. Retry only when the CropScape service is healthy, or provide exact CDL ZIP URLs via `CDL_URLS_FILE`.

## Retry Conditions

Retry with:

```bash
bash staging/usda_cdl_crop_classes_u8/download.sh
```

or with an exact URL TSV:

```text
source_id	url
cdl_2023_fips_10	https://.../some_cdl_file.zip
```

```bash
CDL_URLS_FILE=/path/to/cdl_urls.tsv bash staging/usda_cdl_crop_classes_u8/download.sh
```
