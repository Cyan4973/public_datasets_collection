# NOAA NOS San Francisco Bay Operational Forecast System (SFBOFS, FVCOM) Nowcast 3-D Salinity Fields on the Unstructured Mesh, Native Float32

- Candidate id: `noaa_nos_sfbofs_fvcom_salinity_f32`
- Width: float32
- Quantity: Sea-water salinity (PSU) from the FVCOM hydrodynamic model at every mesh node (54,120 nodes) and sigma layer (about 20). One hourly nowcast output time step per file.
- Source: https://registry.opendata.aws/noaa-ofs/
- Resources: https://noaa-nos-ofs-pds.s3.amazonaws.com/?list-type=2&prefix=sfbofs/netcdf/2025/&delimiter=/, https://noaa-nos-ofs-pds.s3.amazonaws.com/sfbofs/netcdf/2025/06/01/sfbofs.t03z.20250601.fields.n003.nc
- License: NOAA NODD open data: free use and redistribution (U.S. Government data)
- License evidence: https://github.com/awslabs/open-data-registry/blob/main/datasets/noaa-ofs.yaml
- License quote: License: The data may be used and redistributed for free but is not intended for legal use, since it may contain inaccuracies.
- Natural record: One model output time step: the full 3-D salinity(siglay, node) field of one hourly fields.nNNN.nc file
- Estimated samples: 52
- Estimated primary values: 56,000,000
- Estimated download bytes: 2,950,000,000
- Estimated primary bytes: 225,000,000
- Decode path: curl about 52 weekly files (e.g. the t03z n003 nowcast each week of 2025) pinned by size and ETag. Each is 56,605,561 bytes. Parse the NetCDF4/HDF5 object headers in pure Python and read the 'salinity' dataset; the constant file size suggests contiguous, uncompressed storage. Handle deflate if present, as in the STOFS precedent. Optionally range-fetch only the salinity extent after reading the header.
- Novelty kind: new_modality
- Measurement type: sim_ocean_field
- Instrument line: noaa_nos_fvcom_ofs
- Archive collection: noaa-nos-ofs-pds.s3.amazonaws.com
- Novelty evidence: novelty.py --url https://noaa-nos-ofs-pds.s3.amazonaws.com --terms ofs roms fvcom: no URL match. --type sim_ocean_field: 0 families. The existing sim_* families are CFD/PDE/GRMHD (sim_fluid_field), atmospheric (ERA5, ClimSim, GEOS-Chem) and solid mechanics. The NOAA STOFS recipe is 64-bit ADCIRC station water level from a different bucket.
- Homogeneity: One model system (SFBOFS FVCOM), one mesh, one variable, one output type (nowcast fields), one cycle hour, weekly across 2025. FVCOM's unstructured mesh has no land points, which avoids the fill-dominated ROMS grids of CBOFS and similar systems. Do not mix temperature, other OFS domains or forecast hours.
- Risks: Weekly snapshots of the same estuary share mesh ordering, so samples are related but driven by tides and river flow. The siglay count (about 20) is not yet confirmed. Extraction ratio is about 8% of downloaded bytes unless the builder range-reads only the salinity dataset. Smooth fields in node order could sit near other simulated-field families on the byte gate.
- Probe evidence: Bucket listing shows sfbofs/netcdf/ with 2024-2026 folders and 4 cycles per day x n000-n006 fields files, each 56,605,561 bytes. A one-byte range GET returned 206. The first 400 KB header contains strings 'salinity', 'temperature', 'siglay', 'fvcom_grid' and netCDF dimension markers with sizes 102264 (nele) and 54120 (node). The file magic is \x89HDF.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_225934.jsonl`).
