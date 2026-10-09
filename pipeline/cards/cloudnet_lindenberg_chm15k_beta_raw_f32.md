# ACTRIS Cloudnet Lindenberg (DWD) Lufft CHM15k Ceilometer Daily Raw Attenuated Backscatter Profiles (beta_raw), Native Float32

- Candidate id: `cloudnet_lindenberg_chm15k_beta_raw_f32`
- Width: float32
- Quantity: Range-corrected raw attenuated backscatter coefficient beta_raw (sr-1 m-1), time x range-gate (~1024 gates, 15 m) matrix from a single Lufft CHM15k ceilometer at DWD Lindenberg, processed by cloudnetpy (CloudnetArray default dtype f4, zlib-compressed NetCDF4). Unmasked raw field including the noise floor; the masked 'beta' variable is not used.
- Source: https://cloudnet.fmi.fi/search/data?site=lindenberg&product=lidar&instrument=chm15k
- Resources: https://cloudnet.fmi.fi/api/files?product=lidar&instrument=chm15k&site=lindenberg&dateFrom=2024-01-01&dateTo=2024-12-31, https://cloudnet.fmi.fi/api/download/product/<uuid>/<YYYYMMDD>_lindenberg_chm15k_<hash>.nc
- License: CC BY 4.0
- License evidence: https://docs.cloudnet.fmi.fi/
- License quote: Cloudnet data is licensed under a Creative Commons Attribution 4.0 international licence.
- Natural record: One site-day Cloudnet lidar product file, i.e. the full-day beta_raw time x range matrix of one CHM15k instrument
- Estimated samples: 24
- Estimated primary values: 100,000,000
- Estimated download bytes: 915,000,000
- Estimated primary bytes: 400,000,000
- Decode path: curl the per-file downloadUrl from the files API, which pins uuid, filename, size and sha256 checksum. Then parse NetCDF4/HDF5 in pure Python: superblock, object headers, chunk B-tree, then zlib-inflate the chunks (plus shuffle if the filter pipeline says so) of the 'beta_raw' dataset (time, range) as float32. Repo precedents for pure-stdlib HDF5 deflate decoding: mpc_goes18_abi_cmi_c13_fulldisk_u16, noaa_stofs2d (shuffle+deflate), zenodo_lodopab.
- Novelty kind: new_modality
- Measurement type: atmospheric_lidar_backscatter
- Instrument line: lufft_chm15k_ceilometer
- Archive collection: cloudnet.fmi.fi
- Novelty evidence: novelty.py --url https://cloudnet.fmi.fi --terms cloudnet ceilometer cloud_radar: no matches in recipes, registry, ledger or downstream. --type atmospheric_lidar_backscatter: 0 families. The existing laser_range families are surface lidar point attributes, depth maps and range scans, not atmospheric backscatter profiles.
- Homogeneity: One instrument (Lindenberg CHM15k), one product (cloudnetpy lidar), one variable, one unit. Files are spread about 2 per month across 2024 (366 daily files exist). Do not mix CL31/CL51/CL61 or PollyXT instruments, or other sites with different CHM15k firmware or time resolution.
- Risks: The download endpoint ignores HTTP Range: a range GET returned the whole 28 MB file with status 200. Resume is impossible, but files are only 16-47 MB, so download.sh should verify the API sha256 and retry whole files. The beta_raw time dimension (15 s vs 30 s profiles) is not confirmed, so primary bytes per sample are 12-24 MB. Values span many decades with a noise floor around 0, so the byte gate should see a distinctive float pattern, but this is unverified.
- Probe evidence: API GET /api/files?product=lidar&date=2024-06-01 listed 33 lidar files (chm15k at about 20 sites). For Lindenberg chm15k in 2024 it returned 366 files, sizes 15.9-47.4 MB, mean 38.1 MB, each with sha256. /api/products/variables lists lidar-beta_raw. File format reported as 'HDF5 (NetCDF4)'. The cloudnetpy source (cloudnetarray.py) defaults data_type to 'f4', and output.py writes variables with zlib=True. The first 400 KB of 20240601_lindenberg_chm15k shows beta_raw, range and cloudnetpy_version.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_225934.jsonl`).
