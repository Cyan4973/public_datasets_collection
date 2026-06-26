# ESA WorldCover Land-Cover Tiles

This staged recipe collects selected internal tiles from ESA WorldCover 2021 map COGs and emits one `uint8` land-cover class grid per selected internal GeoTIFF tile.

It intentionally uses HTTP range requests instead of full COG downloads. A full official COG raster can be too large to decode wholesale under the repository primary-output cap, while a TIFF internal tile is a real storage chunk and a stable natural boundary for this bounded recipe.

Default knobs:

```sh
WORLDCOVER_HEADER_BYTES=2097152
WORLDCOVER_TILES_PER_SOURCE=8
WORLDCOVER_MAX_PRIMARY_BYTES=950000000
```

You can override the selected source COGs with `WORLDCOVER_URLS_FILE=/path/to/urls.tsv`. The file format is tab-separated:

```text
source_id	url
N00E006	https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N00E006_Map.tif
```

Usage after the user-run external range download:

```sh
bash staging/esa_worldcover_landcover_tiles_u8/download.sh
bash staging/esa_worldcover_landcover_tiles_u8/build.sh
bash staging/esa_worldcover_landcover_tiles_u8/verify.sh
```

Do not promote to `datasets/` until the current `download.sh`, `build.sh`, and `verify.sh` have succeeded locally.
