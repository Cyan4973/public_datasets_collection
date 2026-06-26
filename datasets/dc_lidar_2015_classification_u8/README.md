# DC LiDAR 2015 Classification UInt8

This staged recipe collects uncompressed District of Columbia 2015 classified
LAS point-cloud tiles and emits one native `uint8` classification-code stream
per LAS tile.

Defaults target the public AWS Open Data bucket:

```sh
DC_LIDAR_BUCKET_URL=https://dc-lidar-2015.s3.amazonaws.com/
DC_LIDAR_PREFIX=Classified_LAS/
DC_LIDAR_FILE_LIMIT=3
DC_LIDAR_MAX_FILE_BYTES=500000000
DC_LIDAR_MAX_TOTAL_BYTES=800000000
```

The default downloader lists the LAS prefix and selects the smallest qualifying
`.las` objects, which currently keeps the user-run source download around
650 MB. Increase `DC_LIDAR_FILE_LIMIT` or byte caps if a broader tile subset is
desired.

Usage after the user-run external download:

```sh
bash staging/dc_lidar_2015_classification_u8/download.sh
bash staging/dc_lidar_2015_classification_u8/build.sh
bash staging/dc_lidar_2015_classification_u8/verify.sh
```

Exact key or URL overrides are supported:

```sh
DC_LIDAR_KEYS_FILE=/path/to/keys.txt bash staging/dc_lidar_2015_classification_u8/download.sh
DC_LIDAR_URLS_FILE=/path/to/urls.txt bash staging/dc_lidar_2015_classification_u8/download.sh
```

For LAS point formats 0-5, the build emits the low 5 bits of the historical
classification byte. For LAS point formats 6-10, it emits the native
classification byte. The recipe rejects `.laz` and COPC inputs because those
require an undeclared LASzip decoder.
