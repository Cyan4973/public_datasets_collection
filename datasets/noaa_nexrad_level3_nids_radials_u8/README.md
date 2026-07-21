# NOAA NEXRAD Level-III NIDS Radials UInt8

Recipe for decoded NEXRAD Level-III NIDS digital radial bins.

The default scope is one coherent product code:

- station: `ABC`
- date: `20200408`
- product code: `N0Q`
- limit: `96` product files

The primary output is decoded packet-16 radial bin values, not NIDS message
bytes. The current default products decode to one `360 x 460` uint8 sample per
product file.

Run:

```bash
bash datasets/noaa_nexrad_level3_nids_radials_u8/download.sh
bash datasets/noaa_nexrad_level3_nids_radials_u8/build.sh
bash datasets/noaa_nexrad_level3_nids_radials_u8/verify.sh
```

If public bucket listing fails, provide exact inputs:

```bash
NEXRAD_L3_URLS_FILE=/path/to/urls.tsv \
  bash datasets/noaa_nexrad_level3_nids_radials_u8/download.sh
```

`urls.tsv` format:

```text
name	product_code	url
ABC_N0Q_2020_04_08_00_00_17	N0Q	https://...
```

or provide object keys:

```bash
NEXRAD_L3_KEYS_FILE=/path/to/keys.txt \
  bash datasets/noaa_nexrad_level3_nids_radials_u8/download.sh
```
