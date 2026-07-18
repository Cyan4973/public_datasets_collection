# Numeric New Domains Hunt: NOAA GOES-16 ABI Cloud Mask NetCDF

## Recommendation

Stage `noaa_goes16_abi_cloud_mask_netcdf_u8`, using a bounded sorted prefix
selection of public GOES-16 ABI Level-2 full-disk Cloud Mask NetCDF products
from the Google Cloud public data mirror.

## Why This Adds New Territory

- Domain: operational geostationary satellite cloud-mask products.
- Shape: one complete NetCDF/HDF5 scientific product container per scan.
- Difference from accepted datasets: the catalog has static land-cover rasters,
  weather station series, radar products, and general satellite imagery, but
  not time-resolved GOES ABI cloud-mask product containers.
- Numeric representation: one uint8 byte series per NetCDF product file. This
  keeps the recipe dependency-free because `netCDF4`, HDF5, and NumPy are not
  available in the current environment.

## Materiality

The Google Cloud bucket listing for
`ABI-L2-ACMF/2024/001/00/` showed full-disk product objects around 25-26 MB
each. The default recipe selects up to 24 sorted objects across hours 00-03,
which should produce roughly 600 MB of primary uint8 data while staying below
the repository's 1 GB per-dataset cap.

The recipe enforces:

- max files: 24
- min files: 12
- per-file cap: 50,000,000 bytes
- total download cap: 850,000,000 bytes
- total download floor: 250,000,000 bytes
- primary-output hard cap: 1,000,000,000 bytes

## Script To Run

```bash
bash staging/noaa_goes16_abi_cloud_mask_netcdf_u8/download.sh
```

After the download succeeds, build and verify locally:

```bash
bash staging/noaa_goes16_abi_cloud_mask_netcdf_u8/build.sh
bash staging/noaa_goes16_abi_cloud_mask_netcdf_u8/verify.sh
```

## Rejected Candidates In This Pass

- YouTube-8M would have added video/audio embeddings, but the public storage
  shard URLs returned 403.
- Google Fonts would have added typography/font binaries, but GitHub,
  `fonts.google.com`, `fonts.googleapis.com`, and `fonts.gstatic.com` are
  blocked from this environment.
- Larger Geofabrik OSM PBF extracts would have added map transport bytes, but
  the Geofabrik host is blocked and OSM is already partially represented by
  Taginfo.
- Open Images object segmentation is accessible and large, but it is too close
  to accepted segmentation-label datasets plus the accepted Open Images
  bounding-box annotation recipe.

## Acceptance Outcome

The GOES-16 ABI full-disk Cloud Mask NetCDF selection downloaded, built, and
verified successfully.

- source product: `ABI-L2-ACMF`
- source time window: 2024 day 001, hours 00-03
- downloaded NetCDF/HDF5 products: 24
- downloaded bytes: 602,303,871
- primary samples: 24
- primary values: 602,303,871
- primary bytes: 602,303,871
- container headers: all selected products validated as HDF5-backed NetCDF
- sampled byte diversity: every selected product had all 256 byte values in the
  sampled chunks
- output cap behavior: sorted prefix selection processed; primary output
  remained below the 1 GB cap
