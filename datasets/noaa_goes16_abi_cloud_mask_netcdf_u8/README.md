# NOAA GOES-16 ABI Cloud Mask NetCDF UInt8

Candidate recipe for NOAA GOES-16 ABI Level-2 full-disk Cloud Mask NetCDF
products mirrored in the public Google Cloud `gcp-public-data-goes-16` bucket.

The target material is operational geostationary satellite cloud-mask products.
This dependency-free recipe preserves one complete NetCDF/HDF5 product file as
one uint8 byte-series sample, after validating the public bucket listing, file
sizes, scientific container header, and non-degenerate content. It does not
require `netCDF4`, HDF5, or NumPy.

Run:

```bash
bash staging/noaa_goes16_abi_cloud_mask_netcdf_u8/download.sh
```

Then build and verify locally:

```bash
bash staging/noaa_goes16_abi_cloud_mask_netcdf_u8/build.sh
bash staging/noaa_goes16_abi_cloud_mask_netcdf_u8/verify.sh
```
