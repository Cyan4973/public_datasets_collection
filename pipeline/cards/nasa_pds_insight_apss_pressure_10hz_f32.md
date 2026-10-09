# InSight APSS Pressure Sensor Calibrated Martian Surface Atmospheric Pressure, 10 Hz Full-Sol Records (Pa), Float32

- Candidate id: `nasa_pds_insight_apss_pressure_10hz_f32`
- Width: float32
- Quantity: Calibrated Mars surface atmospheric pressure (Pa, 4 decimals, ~600-900 Pa) from the InSight APSS pressure sensor at 10 samples/s
- Source: https://atmos.nmsu.edu/PDS/data/PDS4/InSight/ps_bundle/
- Resources: https://atmos.nmsu.edu/PDS/data/PDS4/InSight/ps_bundle/data_calibrated/, https://atmos.nmsu.edu/PDS/data/PDS4/InSight/ps_bundle/data_calibrated/sol_0390_0477/ps_calib_0420_02.csv, https://atmos.nmsu.edu/PDS/data/PDS4/InSight/ps_bundle/data_calibrated/collection_ps_data_calibrated_inventory.tab
- License: NASA PDS public scientific data (LicenseRef-NASA-SMD-Open-Data)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: It is Science Mission Directorate (SMD) policy, consistent with NASA and Federal policies, that information produced from SMD-funded scientific research activities be made publicly available.
- Natural record: One sol product ps_calib_<SOL>_<ver>.csv (PDS4 table); 10 Hz full-sol files hold 887,768 rows
- Estimated samples: 40
- Estimated primary values: 35,500,000
- Estimated download bytes: 3,500,000,000
- Estimated primary bytes: 142,000,000
- Decode path: csv module over the PDS4 delimited table; take the PRESSURE column (field 6) as float32 in row order, filter rows where PRESSURE_FREQUENCY == 10.0, and select sols whose file is entirely 10 Hz (the 87 MB files). Blank pressure fields are dropped and the drops documented. PRESSURE_TEMP is a separate 0.2 Hz quantity and is excluded.
- Novelty kind: new_source
- Measurement type: met_station_obs
- Instrument line: insight_apss_pressure_sensor
- Archive collection: atmos.nmsu.edu/PDS/data/PDS4/InSight/ps_bundle
- Novelty evidence: novelty.py --url/--terms InSight/APSS/Mars pressure: no recipe, registry, ledger or downstream matches; host atmos.nmsu.edu (PDS Atmospheres node) unused by the corpus. No planetary-meteorology family exists. Barometric pressure appears only as noaa_coops_air_pressure f64 and open_meteo reanalysis.
- Homogeneity: One sensor, one unit (Pa), one cadence: only 10 Hz full-sol files (496 of 932 files are the 87 MB 10 Hz type). Exclude the 2 Hz / 20 Hz and partial-sol files to keep one tick and cadence regime.
- Risks: Poor extraction ratio (~25:1 CSV text to float32), but absolute kept signal (~140 MB) is large and no binary product exists (data_raw is also CSV, same size). Download ~3.5 GB, within the 5 GB cap; use resumable curl. The decimal-quantized, slowly varying float32 series might sit close to fingrid grid-frequency or USGS geomag f32 in zlsim (different grid: 1e-4 Pa at ~700 vs 1e-3 Hz at 50); breadth is uncertain. float32 ulp at ~700 Pa is 6.1e-5, below the 1e-4 source resolution.
- Probe evidence: Listings of 14 sol_* dirs under data_calibrated: 932 CSV products, 496 at 87 MB. ps_calib_0420_02.xml: records=887768. Range GET of the head: PRESSURE 638.8091, PRESSURE_FREQUENCY 10.0. Mid-file (offset 40 MB) PRESSURE 625.7403 at 10.0 Hz. Older sol 150 file at 2.0 Hz (17 MB).

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_183620.jsonl`).
