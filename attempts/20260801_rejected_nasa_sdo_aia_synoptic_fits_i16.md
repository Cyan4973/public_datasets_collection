# Rejected: NASA SDO/AIA Synoptic FITS Int16 — Logical Images Are Scaled Int32

- Date: 2026-08-01
- Candidate: `staging/nasa_sdo_aia_synoptic_fits_i16`
- Intended domain: Solar Dynamics Observatory AIA EUV/UV synoptic imagery
- Intended width: native unscaled signed-int16 FITS image planes

## Discovery repair

The earlier data.gov route exposed no FITS payloads. A new metadata-only
preflight crawled the official direct JSOC synoptic directory at:

`https://jsoc1.stanford.edu/data/aia/synoptic/`

The bounded crawl visited 160 directory pages and found the ten current
`AIAsynoptic*.fits` products, one per AIA wavelength. It fetched only the first
64 KiB of each file, sufficient to inspect the empty primary HDU and the first
tile-compressed image extension. No complete FITS product was downloaded.

## Header findings

All ten products have the same relevant structure:

- primary HDU: `BITPIX=8`, `NAXIS=0` (no image payload)
- image storage: tiled-compressed FITS binary-table extension
- logical image type: `ZBITPIX=32`
- logical image geometry: `ZNAXIS=2`, `1024 × 1024`
- scaling: `BSCALE=0.0625`, `BZERO=0`

The solar pixels are therefore not native int16 values. Their logical stored
representation is scaled int32, and accessing it would also require a decoder
for the tile-compressed FITS table. Reinterpreting the compressed table bytes
or narrowing the logical int32 values to int16 would violate the typed-value
and native-width rules.

The candidate is rejected for the 16-bit corpus. It is not automatically
reclassified as a 32-bit family because the meaningful image values require
scaling and the repository lacks the necessary compressed-FITS tile decoder.
A future 16-bit attempt must use a different SDO/AIA product series whose FITS
headers explicitly declare unscaled `BITPIX=16` or `ZBITPIX=16` image data.

Evidence:

- `.data/logs/nasa_sdo_aia_synoptic_fits_i16/discover_jsoc.latest.log`
- `.data/discovery/nasa_sdo_aia_synoptic_fits_i16/header_preflight.tsv`
- `.data/discovery/nasa_sdo_aia_synoptic_fits_i16/summary.json`
