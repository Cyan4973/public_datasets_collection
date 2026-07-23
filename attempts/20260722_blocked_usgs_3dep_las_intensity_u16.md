# Blocked: usgs_3dep_las_intensity_u16 — seed has no direct .las

- Date: 2026-07-22
- Candidate: `staging/usgs_3dep_las_intensity_u16`
- Domain: airborne LiDAR intensity uint16

## Attempt

```
bash staging/usgs_3dep_las_intensity_u16/download.sh
```

Log: `.data/logs/usgs_3dep_las_intensity_u16/download.latest.log`

```
no candidate URLs discovered; provide URL list or adjust seed selectors
```

Seed: `https://registry.opendata.aws/usgs-lidar/` — page is a markdown description with S3 bucket info, not HTML hrefs to `.las` files.

`urls.txt` does not exist.

## Reason

`bounded_url_download.py` scrapes `<a href>` for suffix `.las`. Registry page contains no direct `.las` links, only links to S3 console. Real `.las` files live in `s3://usgs-lidar-public/` bucket, requiring S3 ListObjectsV2 XML parsing, not simple href scraping. Also most public bucket now serves `.laz` COPC, not uncompressed `.las`.

## Retry

- Implement S3 listing parser: fetch `https://usgs-lidar-public.s3.amazonaws.com/?list-type=2&max-keys=1000&prefix=...` parse `<Key>` for `.las` and download via `https://usgs-lidar-public.s3.amazonaws.com/{key}`
- Or pin exact direct `.las` URLs via `USGS_3DEP_LAS_URLS_FILE` with known small tiles, e.g., from `https://usgs-lidar-public.s3.amazonaws.com/MD_CityOfBaltimore_2015/...`
- Also need to handle that parser rejects `.laz`, so must filter to `.las` only.

## Value

Lidar intensity radiometry at 1064 nm, distinct from elevation raster and microscopy.

