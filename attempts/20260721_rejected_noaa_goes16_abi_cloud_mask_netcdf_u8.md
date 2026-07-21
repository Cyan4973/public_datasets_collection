# noaa_goes16_abi_cloud_mask_netcdf_u8

- Date: 2026-07-21
- Status: rejected
- Candidate dataset: NOAA GOES-16 ABI Level-2 Cloud Mask NetCDF/HDF5 product bytes as uint8.
- Source: https://storage.googleapis.com/gcp-public-data-goes-16/ABI-L2-ACMF/
- Why it looked promising: Public NOAA operational geostationary satellite cloud-mask products with large product files and coherent per-scan boundaries.
- Failure class: opaque_container_bytes
- What happened: The accepted recipe copied complete NetCDF/HDF5 `.nc` files as raw `uint8` byte-series samples instead of decoding the actual cloud-mask variable. The emitted values were container serialization bytes: HDF5 headers, metadata, object tables, chunk indexes, attributes, and possibly compressed data chunks mixed with science arrays.
- Evidence: The manifest used `representation_class = "container_bytes"`, `sample_format = "complete NetCDF/HDF5 product file bytes"`, and `conversion = "Copy each complete source NetCDF/HDF5 product file unchanged..."`. Local realized output had 24 samples and 602,303,871 primary bytes, but those bytes were opaque product containers rather than native cloud-mask `uint8` grid values.
- Decision: Remove `noaa_goes16_abi_cloud_mask_netcdf_u8` from `datasets/` and reject the byte-container recipe. A `uint8` primary series must be an actual source numeric or symbolic 8-bit measurement series, not arbitrary serialized file bytes.
- Retry conditions: Retry only with a reproducible NetCDF/HDF5 decoding path that extracts the actual cloud-mask variable or another documented native 8-bit product variable with real measurement semantics.
