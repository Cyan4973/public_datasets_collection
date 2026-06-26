# NOAA NEXRAD Level-III Products

This staged recipe collects a bounded set of one coherent NEXRAD Level-III product code and emits one `uint8` product-message payload sample per file.

Defaults:

```sh
NEXRAD_L3_BUCKET_URL=https://unidata-nexrad-level3.s3.amazonaws.com/
NEXRAD_L3_STATION=ABC
NEXRAD_L3_DATE_YYYYMMDD=20200408
NEXRAD_L3_PRODUCT_CODE=N0Q
NEXRAD_L3_FILE_LIMIT=96
```

The Unidata bucket currently exposes flat object keys such as
`ABC_N0Q_2020_04_08_00_00_17`; the defaults target that known layout. The
downloader also tries several directory-style Level-III prefix layouts. If the
public bucket listing or default prefixes are wrong for the current archive,
provide exact inputs:

```sh
NEXRAD_L3_URLS_FILE=/path/to/urls.tsv bash staging/noaa_nexrad_level3_products_u8/download.sh
```

`urls.tsv` format:

```text
name	product_code	url
ABC_N0Q_20200408_0000	N0Q	https://...
```

or provide object keys:

```sh
NEXRAD_L3_KEYS_FILE=/path/to/keys.txt bash staging/noaa_nexrad_level3_products_u8/download.sh
```

Usage after the user-run external download:

```sh
bash staging/noaa_nexrad_level3_products_u8/download.sh
bash staging/noaa_nexrad_level3_products_u8/build.sh
bash staging/noaa_nexrad_level3_products_u8/verify.sh
```

Do not promote to `datasets/` until the current `download.sh`, `build.sh`, and `verify.sh` have succeeded locally.
