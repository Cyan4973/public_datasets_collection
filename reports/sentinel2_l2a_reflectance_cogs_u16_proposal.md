# Sentinel-2 L2A Reflectance COG Uint16 Proposal

## Candidate

`sentinel2_l2a_reflectance_cogs_u16` targets Element84 Sentinel-2 Level-2A
Cloud Optimized GeoTIFFs from the public `sentinel-cogs` bucket.

This is a genuinely different 16-bit modality from the current validated set:
multispectral optical satellite surface reflectance, not medical CT, radar
precipitation, mesh indices, audio, or neural-network tensors.

## License / Access

- Source: `https://sentinel-cogs.s3.us-west-2.amazonaws.com/`
- Access: free public S3 HTTP endpoint, not requester-pays.
- License / terms: Copernicus Sentinel Data Terms and Conditions.
- Safety: public remote-sensing imagery, no personal data.

## Default Bounded Selection

The staged recipe queries Element84 Earth Search during user-run download and
writes exact `sentinel-cogs` HTTPS asset URLs to `download_plan.tsv`.

Default target:

- `2` low-cloud scenes.
- `3` bands per scene.
- Bands: `blue_10m`, `rededge1_20m`, `coastal_60m`.
- Expected natural samples: `6`, one sample per source band raster.
- Expected raw primary output:
  - `2 x 10m` bands: about `482 MB`.
  - `2 x 20m` bands: about `121 MB`.
  - `2 x 60m` bands: about `13 MB`.
  - Total expected primary output: about `616 MB`, under the `1 GB` cap.

The mixed native resolutions intentionally avoid an all-same-size raster set.

## Parser / Validation

The build is standard-library only. It supports classic TIFF COGs with:

- single-band `uint16` samples,
- uncompressed or Deflate-compressed strips/tiles,
- TIFF horizontal predictor `1` or `2`,
- classic TIFF offsets/counts.

Unsupported compression, non-uint16 assets, malformed tile tables, truncated
tiles, empty rasters, and constant rasters are rejected.

## Current State

Validated and promoted to `datasets/sentinel2_l2a_reflectance_cogs_u16`.

The first user download attempt failed before source selection because Python
`urllib` did not inherit the local `~/.curlrc` proxy settings and could not
resolve `earth-search.aws.element84.com`. The download script now mirrors the
curl proxy fallback used by other repository helpers before querying Element84
Earth Search.

The second user download run succeeded. Local build and verify then succeeded:

- compressed source bytes: `98,891,975`
- primary samples: `6`
- primary values: `308,098,800`
- primary bytes: `616,197,600`
- scenes: `2`
- bands per scene: `blue_10m`, `rededge1_20m`, `coastal_60m`
- sample shapes: `10980x10980`, `5490x5490`, `1830x1830`
- TIFF encoding: tiled Deflate COGs with horizontal predictor
- natural sample boundary: one source band raster

Verified command sequence:

```bash
datasets/sentinel2_l2a_reflectance_cogs_u16/download.sh
datasets/sentinel2_l2a_reflectance_cogs_u16/build.sh
datasets/sentinel2_l2a_reflectance_cogs_u16/verify.sh
```
