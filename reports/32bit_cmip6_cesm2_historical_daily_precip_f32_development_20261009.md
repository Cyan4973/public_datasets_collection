# CMIP6 CESM2 historical daily precipitation flux float32 development

## Outcome

Accepted `cmip6_cesm2_historical_daily_precip_f32`. It holds all 3650 daily-mean global precipitation-flux fields (`pr`) from one pinned decade file (1940-1949). The file is the CMIP6 NCAR CESM2 *historical* run, ensemble member `r1i1p1f1`, native grid `gn`, dataset version `v20190401`.

This is the corpus's first output from a free-running coupled climate model, and its first precipitation-flux grid:
- The nearest local f32 family, `weatherbench2_era5_pressure_level_fields_f32`, holds smooth reanalysis state fields (T/U/V/Z/Q/W) and no precipitation.
- The existing precipitation families are point series (Open-Meteo f32, NASA POWER f64, ISD/GHCN at 16 bits) or regional radar (`dwd_radolan_rw_precip_i16`).

zlsim measured the breadth as OK. The nearest family is downstream `h1__collection2._0.lhpi`, an unrelated H1 particle-physics column, at distance 0.0926.

## Source and rights

- Source: anonymous `s3://esgf-world` (AWS Registry of Open Data entry `cmip6`), the ESGF NetCDF mirror of CMIP6.
- Object: `CMIP6/CMIP/NCAR/CESM2/historical/r1i1p1f1/day/pr/gn/v20190401/pr_day_CESM2_historical_r1i1p1f1_gn_19400101-19491231.nc`
- Bytes: 663,390,696
- S3 multipart ETag: `accfa4a438ca6393474430698d9489dd-80`
- SHA-256: `fce6d860a9e01b259b9534150392681c0766c6e904814737ad9ea657e36addba`
- tracking_id: `hdl:21.14100/c9b7ee29-8ac2-46d4-9e5c-b309b1ef0999`
- License: CC BY 4.0
- Citation: Danabasoglu, G. (2019), NCAR CESM2 model output prepared for CMIP6 CMIP historical, doi:10.22033/ESGF/CMIP6.7627

The licence evidence:
- The official WCRP CMIP6 source_id licence table lists CESM2 (NCAR) as "CC BY 4.0", with history "2019-02-18: initially published under CC BY-SA 4.0; 2022-06-16: relaxed to CC BY 4.0".
- The DataCite record for the exact dataset DOI lists Creative Commons Attribution 4.0 International.
- The PCMDI CMIP6 Terms of Use record the October 2022 relaxation.

The 2019 file still embeds its original CC BY-SA 4.0 notice. The manifest records both readings. A conservative share-alike reading has repo precedent.

## Shape and conversion

Each natural record is one model output time step: a daily-mean 192 x 288 (lat x lon) field of 55,296 values. The `pr` variable is little-endian IEEE float32, stored as one HDF5 chunk per day with the shuffle(4) then deflate pipeline and indexed by a v1 B-tree.

The pure-stdlib reader `scripts/h5lite.py` is copied unchanged in logic from the accepted geoschem recipe and checks lookup3 checksums on metadata blocks. Each chunk is inflated and unshuffled, and the stored float32 values are written unchanged. There is no scaling, regridding, thinning or remapping.

Build and verify both check:
- the global attributes (model, experiment, member, variable, grid, tracking_id);
- the datatype, chunking and filter pipeline;
- units, standard_name and cell_methods, and the 1e20 fill value;
- the noleap time axis (time[i] = 707735 + i, bounds (t-1, t));
- the lat/lon coordinates;
- that the chunk index is complete.

Any fill value, NaN, Inf, or degenerate field is fatal.

## Accepted output

- Primary samples: 3,650 (one per model day, 19400101..19491231)
- Primary values: 201,830,400
- Primary bytes: 807,321,600
- Sample size: 55,296 values (221,184 bytes) each
- Value range: 0 to 6.117e-3 kg m-2 s-1
- Exact zeros: 0.879% of values (25 to 1,579 per day, median 483)
- Negatives, fill, NaN, Inf: none
- Distinct values per day: 53,459 to 55,151 (median 54,580)
- Unique sample SHA-256 digests: 3,650

## Judge checks

- `gate.py staging/cmip6_cesm2_historical_daily_precip_f32`: PASS, no warnings.
- I ran `verify.sh` myself: exit 0. The self-test passed, all 3650 samples byte-matched a fresh decode through the creation-order index, the 11 independent unshuffle spot checks passed, and the manifest totals matched.
- No network calls or credentials appear in build, verify or the scripts. `scripts/h5lite.py` differs from the accepted geoschem copy only in its docstring.
- Byte inspection with stdlib `array`/`struct` on 6 days across the decade:
  - The area-weighted global mean is 2.81–3.16 mm/day, which is physically correct. The tropics are 4.2–6.1 mm/day and the poles 0.4–0.9 mm/day.
  - Zeros cluster over the Sahara, Sahel, Arabia and inland Australia, so the orientation is correct.
  - Lag-1 and lag-288 correlations are 0.91 and 0.88, against 0.095 at stride 192, so the lat x lon order is correct.
  - There are no denormals. Lane 3 uses 40 exponent bytes, so the float32 width is honest.
  - Adjacent days differ by about 0.90 relative L2, so there are no near-duplicates.
- Rights: I fetched the live WCRP licence table row for CESM2 (CC BY 4.0 with the relaxation history) and the DataCite API record for DOI 10.22033/ESGF/CMIP6.7627 (cc-by-4.0).
- `novelty.py`:
  - The URL and term checks (cmip6, cesm2, esgf, precipitation_flux) found no local, registry or downstream matches.
  - The `sim_atmos_field` type holds only ERA5 f32, ClimSim f64 and GEOS-Chem f64.
  - No other family shares the instrument line or archive.
- Volume: 807 MB is the whole natural population of the single pinned file. It is under the 1 GB cap and comparable to other accepted large recipes.
