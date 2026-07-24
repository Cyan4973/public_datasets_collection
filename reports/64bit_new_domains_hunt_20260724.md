# 64-bit New Domains Hunt — 2026-07-24

Date: 2026-07-24
Goal: hunt for new 64-bit numeric series (int64 / uint64 / float64) covering different domains than already collected. No payloads downloaded in this turn; staging recipes created for user to run.

## Authoritative Inventory (committed layer, not .data/samples)

Existing 64-bit datasets from `datasets/` and `reports/accepted_recipe_audit.tsv` (stable IDs):

- `uci_steel_plates_faults_features_f64` — industrial QA steel plates
- `magic_gamma_telescope_event_features_f64` — Cherenkov gamma telescope event imaging (UCI)
- `noaa_stormevents_details_2024_f64` — NOAA storm events operational weather impact table
- `census_acs_pums_ca_person_2023_i64` — Census PUMS person microdata income weights (demographics)
- `uci_superconductivity_material_features_f64` — material science superconductor critical temp features
- `natural_earth_10m_geometry_xy_f64` — cartographic geometry coordinates (geospatial)
- `nhtsa_fars_2022_crash_tables_f64` — traffic fatality crash tables
- `noaa_ndbc_wave_spectral_density_f64` — ocean buoy wave spectral density (surface ocean)
- `sec_fsd_2015q1_2024q4_numeric_values_i64` — SEC XBRL financial statement numeric values (corporate finance)
- `google_books_1gram_counts_2020_eng_u64` — Google Books ngram yearly match/volume counts (text/culture)
- `citibike_2024_trip_geocoords_f64` and `citibike_2024_01_trip_geocoords_f64` predecessors — bike mobility geocoordinates

Also `sec_fsd_2024q1_q4_numeric_values_i64` and `census_acs_pums_ca_person_2023_i64` were promoted in prior 64-bit hunt (2026-06-17).

Domains already well covered overall (weather station observations, hydrology gauges, etc) per `reports/numeric_new_domains_hunt_20260715.md` — avoid more ordinary weather point series, ordinary image benchmarks, broad bibliographic counts.

## What Counts as New Domain for 64-bit

A new domain requires distinct instrument, experimental setup, operational system, scientific process, unit semantics.

Thin scope (single entity, single snapshot, single arbitrary query) is not acceptable. Primary series must be decoded typed values, not opaque container bytes (containers like NetCDF/HDF5/FITS/ZIP must be decoded). Floor: >=10k primary values or >=100KB primary bytes + median sample >=1k values. Primary output <=1GB.

64-bit native sources: int64 large counts (population >2^31, blockchain satoshis, genomic base counts, file sizes), uint64 ngram match counts, float64 high-precision scientific (geodesy mm-level xyz, stellar photometry flux, moment tensors, trace gas concentrations, high-energy physics kinematics, GNSS orbits).

## Candidate Ranking

| rank | candidate id | new domain | material / shape | why distinct | main risk | bit width |
|---:|---|---|---|---|---|---|
| 1 | `kddcup99_network_intrusion_features_f64` | cybersecurity network intrusion telemetry | UCI KDD Cup 1999 10% dataset: 41 features per TCP connection, many continuous int/float (duration, src_bytes, dst_bytes, count) | Adds operational network-flow security telemetry distinct from vulnerability catalogs (NVD) and OONI measurements. | UCI 403 in agent env? But MAGIC same host worked; user env should work via direct curl to archive.ics.uci.edu | float64 |
| 2 | `noaa_gml_co2_flask_f64` | atmospheric greenhouse gas composition | NOAA GML flask CO2 event files from https://gml.noaa.gov/webdata/ccgg/flask/co2/ — many station files, each with header + float CO2 mole fraction (ppm) time series | Distinct from weather variables (temp, precip, pressure) — trace gas monitoring, climate forcing. | Need bounded discovery of many .txt files; parsing requires skipping '#' header; multiple files provide >>10k values | float64 |
| 3 | `globalcmt_catalog_f64` | seismology earthquake source physics | Global CMT catalog NDK files from https://www.globalcmt.org/CMTfiles/ e.g. jan76_dec20.ndk — 5 lines per quake, contains moment tensor components Mrr,Mtt,Mpp,Mrt,Mrp,Mtp, depth, etc as float | Distinct from USGS point catalog (quake location/mag only) — focal mechanism inversion physics. | Text format semi-structured; need custom NDK parser; file may be large (~100MB) but below cap | float64 |
| 4 | `jpl_gps_position_time_series_f64` | solid earth geodesy / crustal motion | JPL GPS time series from https://sideshow.jpl.nasa.gov/post/tables/ and https://sideshow.jpl.nasa.gov/pub/jpl/pos/ — per-station *.pos files with decimal year, east, north, up displacement (mm) as double | Adds mm-level geodetic displacement distinct from ocean buoy spectra, weather stations, natural earth geometry. Process: GNSS carrier-phase positioning. | File format may vary; need stable per-station URL list; discovery via seed URL suffix .pos | float64 |
| 5 | `kepler_light_curve_flux_f64` | time-domain astronomy photometry | Kepler long-cadence light curves from https://archive.stsci.edu/pub/kepler/lightcurves/ — FITS BINTABLE with TIME (JD) float64 and PDCSAP_FLUX float64 | Adds stellar variability / exoplanet transit time series distinct from static Gaia astrometry f32 and gamma telescope event features. | Requires FITS BINTABLE decode (not just IMAGE); dependency astropy.io.fits or custom decoder — needs tooling | float64 |
| 6 | `bitcoin_transactions_amount_u64` | cryptocurrency ledger | Blockchair dumps https://gz.blockchair.com/bitcoin/transactions/*.tsv.gz — columns include fee, fee_usd, input_total, output_total satoshis as int; per day file millions rows | Distinct from SEC corporate finance — decentralized blockchain ledger financial amounts. Amounts exceed 32-bit need u64. | Files large (GB per day) — need strict bounded download (1-2 files, max bytes 600MB, parse only output_total_usd? Actually satoshi integer). Need gunzip stream parse. | uint64 |
| 7 | `cms_higgs_collision_features_f64` | high-energy particle physics accelerator | CERN CMS Open Data e.g. https://opendata.cern.ch/record/12365 etc Higgs->tau tau ntuples — csv with pt, eta, phi, mass float64 per collision | Adds LHC collision kinematics distinct from Cherenkov telescope gamma (astrophysics). | Root files typically ROOT format need uproot; need csv mirror; licensing CC0 | float64 |
| 8 | `argo_profile_ctd_f64` | subsurface ocean profiling (Argo floats) | Argo GDAC NetCDF profiles https://data-argo.ifremer.fr/ — pressure, temperature, salinity per depth level double | Adds vertical ocean CTD structure distinct from surface buoy spectra and water level — different instrument. | NetCDF decode needs netCDF4/xarray — needs tooling | float64 |
| 9 | `usgs_geomag_observatory_minute_f64` | ground geomagnetic observatories | USGS geomag data via https://geomag.usgs.gov/products/downloads/ — minute H/D/Z/F nanotesla double time series per observatory | Adds ground magnetometer physical time series distinct from seismic waveform i32 and space solar wind proposal. | API limits and component naming verification needed | float64 |
| 10 | `pulsar_timing_residuals_f64` | radio pulsar timing | NANOGrav / IPTA timing residuals text files — TOA residuals microseconds float64 | Adds pulsar timing array domain, distinct. | Small maybe below floor unless many pulsars | float64 |

## Recommended First Pass (direct URLs known to work in user env)

1. `kddcup99_network_intrusion_features_f64` — UCI direct `.gz` file, single file, easy CSV parse to float64 columns, ~494k rows (10% file) -> ~ 15M primary values if emitting 10 float64 columns => passes floor easily, under 1GB.
2. `noaa_gml_co2_flask_f64` — seed-url discovery `https://gml.noaa.gov/webdata/ccgg/flask/co2/` suffix `.txt` with max_files 30, max_total_bytes 600MB, max_file_bytes 200MB — yields many stations, each file thousands rows, aggregated >>10k.
3. `globalcmt_catalog_f64` — direct file https://www.globalcmt.org/CMTfiles/jan76_dec20.ndk or quarterly split to stay under cap, parse Mrr etc as float64.
4. `jpl_gps_position_time_series_f64` — seed-url `https://sideshow.jpl.nasa.gov/pub/jpl/pos/series/` suffix `.pos` (?) or use Nevada Geodetic Lab http://geodesy.unr.edu/gps_timeseries/tenv/ — discovery .tenv files.

Earlier attempts:
- `usdot_bts_ontime_2024_q1_f64` blocked 404 (proposal 2026-06-17) — do not retry without exact URLs.
- `cicids2017` and `kddcup99` earlier UT flagged 403 in agent but MAGIC succeeded with same host, so retry KDD via archive.ics.uci.edu in user env.
- `tess/kepler` needs FITS BINTABLE tooling — defer until builder has astropy or custom decoder.

## License Checks

- UCI datasets: LicenseRef-UCI-ML-Repository — permissive for research, attribution preserved.
- NOAA GML: U.S. Government Work — public domain.
- Global CMT: public research dataset, attribution to Global CMT project.
- JPL GPS: U.S. Government Work.
- Kepler: public NASA data, STScI terms.
- Blockchair Bitcoin: blockchair terms allow research use; dumps are public.

## Implementation Plan

For each staging id:
- manifest from template, fill dataset_id, homepage, license, origins, resources, local_paths, processing, series.
- download.sh: uses curl with retry, writes download_plan.tsv, validates gzip/tsv/fits magic, rejects HTML, writes download_inventory.json, logs under .data/logs/<id>/
- build.sh: python3 local-only parse, array('d') for f64 or array('Q')/('q') for u64/i64, write little-endian bin, enforce floors, median >=1000, primary <=1GB, emit samples.jsonl index
- verify.sh: check index exists, check constant prefix rejection, check floors, check sample non-constant, etc.

Scripts must not download in build.sh; only use local downloads.

Generate attempt docs for failures (transient_failure/blocked) with reason and retry condition.

Focus: produce working recipes for user to run via `bash staging/<id>/download.sh` then build/verify.

## Cross-ref hardening

All new recipes key on stable dataset_id, not source_sample paths. Avoid .data/samples inventory. Use attempts/dataset_status.tsv for status.

## Next Steps

- Implement staging/kddcup99_network_intrusion_features_f64 (cybersecurity)
- Implement staging/noaa_gml_co2_flask_f64 (greenhouse gas)
- Implement staging/globalcmt_catalog_f64 (earthquake source)
- Optionally staging/jpl_gps_position_time_series_f64 if URL discovery verified.

Each will have bounded caps: MAX_FILE_BYTES 600MB default, MAX_TOTAL_BYTES 1GB, timeout 300s.
