# CMIP6 NCAR CESM2 Historical r1i1p1f1 Daily Global Precipitation Flux (pr, 0.9x1.25 deg) Fields, Native Float32

- Candidate id: `cmip6_cesm2_historical_daily_precip_f32`
- Width: float32
- Quantity: Daily-mean precipitation flux pr (kg m-2 s-1) on the CESM2 native 192x288 lat-lon grid, from the CMIP6 historical experiment, member r1i1p1f1
- Source: https://registry.opendata.aws/cmip6/
- Resources: https://esgf-world.s3.amazonaws.com/?list-type=2&prefix=CMIP6/CMIP/NCAR/CESM2/historical/r1i1p1f1/day/pr/, https://esgf-world.s3.amazonaws.com/CMIP6/CMIP/NCAR/CESM2/historical/r1i1p1f1/day/pr/gn/v20190401/pr_day_CESM2_historical_r1i1p1f1_gn_19400101-19491231.nc
- License: CC BY-SA 4.0 (per the file's global license attribute; CMIP6 Terms of Use)
- License evidence: https://pcmdi.llnl.gov/CMIP6/TermsOfUse
- License quote: CMIP6 model data produced by <The National Center for Atmospheric Research> is licensed under a Creative Commons Attribution-[]ShareAlike 4.0 International License (https://creativecommons.org/licenses/).
- Natural record: One model output time step: one daily global pr field (192 x 288 = 55,296 float32 values)
- Estimated samples: 3,650
- Estimated primary values: 201,830,400
- Estimated download bytes: 663,400,000
- Estimated primary bytes: 807,321,600
- Decode path: curl one pinned decade file (about 663 MB; or two decades keeping alternate days) from the anonymous esgf-world bucket, pinned by size and ETag. Pure-Python NetCDF4/HDF5 parse: chunk B-tree, then zlib-inflate (plus shuffle if present) of the 'pr' dataset (time, lat, lon) float32. Emit one sample per daily field.
- Novelty kind: new_source
- Measurement type: sim_atmos_field
- Instrument line: ncar_cesm2_climate_model
- Archive collection: esgf-world.s3.amazonaws.com
- Novelty evidence: novelty.py --url esgf-world --terms cmip6 cesm2 precipitation_flux: no matches anywhere. The sim_atmos_field type has weatherbench2 ERA5 pressure-level state fields (f32: T/U/V/Z/Q/W), ClimSim f64 and GEOS-Chem f64, but no free-running climate model and no precipitation field. Precipitation is sparse and heavy-tailed, unlike smooth pressure-level state fields.
- Homogeneity: One model (CESM2), one experiment, member and grid, one variable, one daily frequency, one dataset version (v20190401). Do not mix other models, members or variables.
- Risks: Same broad type (sim_atmos_field) as the ERA5 f32 family, though statistics should differ. The file's license is BY-SA, which is accepted precedent in this repo (exomol, ahmedml, goose). Primary output from a full decade file is about 807 MB, near but under the cap; the builder may thin to alternate days. HDF5 chunk layout is unverified.
- Probe evidence: S3 ListObjectsV2 lists pr_day_CESM2_historical_r1i1p1f1_gn_* decade files from 1850, about 663 MB each. A 128 KB range GET of the 1940-1949 file shows \x89HDF magic and the global license string quoted above. The AWS registry cmip6.yaml lists esgf-world as an anonymous us-east-2 bucket with a CSV catalog at cmip6-nc.s3.amazonaws.com/esgf-world.csv.gz.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_225934.jsonl`).
