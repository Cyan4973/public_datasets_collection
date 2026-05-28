# noaa_oisst_v2_1_daily

- Date: 2026-05-28
- Status: needs_tooling
- Candidate dataset: NOAA Optimum Interpolation Sea Surface Temperature (OISST) v2.1 daily
- Source:
  - `https://www.ncei.noaa.gov/products/optimum-interpolation-sst`
  - `https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/`
- Why it looked promising:
  - public U.S. government climate data
  - large-scale numeric gridded arrays
  - stable long-running product family
  - useful coverage beyond station and API-style tabular sources
- Failure class:
  - local toolchain gap
  - implementation cost disproportionate to current repo conventions
- What happened:
  - The candidate depends on netCDF4/HDF-style parsing.
  - The current environment does not provide Python libraries such as
    `netCDF4`, `xarray`, `h5py`, or even `numpy`.
  - The current environment also does not provide command-line tooling such as
    `ncdump`, `h5dump`, `cdo`, or `gdalinfo`.
  - Under the current repository norms, introducing a recipe that claims to
    support OISST without a real parser would be weak engineering and likely
    produce a brittle or misleading implementation.
- Evidence:
  - `python3` import preflight reported:
    - `netCDF4 no`
    - `xarray no`
    - `h5py no`
    - `numpy no`
  - command-line tool preflight found no installed path for:
    - `ncdump`
    - `h5dump`
    - `cdo`
    - `gdalinfo`
- Logs:
  - no dataset download attempted
  - no acquisition logs generated
- Decision:
  - reject for now
- Retry conditions:
  - retry if the repository adopts a supported netCDF/HDF parsing path, for example:
    - an approved Python dependency set for gridded-science formats, or
    - an approved command-line extraction toolchain available in the environment
  - retry if we define a repo-level pattern for large gridded tensor products so
    recipes do not each reinvent format handling independently
