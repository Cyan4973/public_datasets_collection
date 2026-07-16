# Numeric New-Domain Hunt

Date: 2026-07-15

Goal: identify public numeric series, any width, that add domains or data
generating processes not already well represented by the accepted collection.
No dataset acquisition was performed for this review.

## Current Coverage To Avoid

The accepted set already has substantial coverage in these areas:

- weather station observations, hydrology gauges, coastal buoys, radar products,
  remote-sensing rasters, terrain, land cover, and planetary rasters
- financial markets, company filings, bibliometrics, public catalog metadata,
  government event tables, transportation station/trip tables, and sports events
- images, label rasters, CT slices, depth frames, speech/audio, seismic windows,
  ECG/EEG waveforms, genomic positions, sequence quality, alignments, proteins,
  molecular coordinates, model weights, sparse matrices, and token/code streams

Promising new material should therefore come from a distinct instrument,
experimental setup, operational system, or scientific process rather than another
variant of a catalog count, weather point series, broad image dataset, or
ordinary geospatial raster.

## Top Candidates

| rank | candidate id | new domain | primary target | natural sample | why it adds variety | main risk |
|---:|---|---|---|---|---|---|
| 1 | `noaa_swpc_dscovr_solar_wind_f32` | spacecraft plasma / magnetometer telemetry | NOAA SWPC DSCOVR recent solar-wind plasma and magnetic-field values as `float32` | one product-field recent high-cadence telemetry stream | Adds continuous heliophysics instrument telemetry, distinct from event catalogs such as DONKI flares/CMEs and from terrestrial weather. | Recent-feed cadence or missing values may vary; verify should accept field-wise streams without requiring identical lengths. |
| 2 | `usgs_geomag_observatory_minute_f32` | geomagnetic observatory data | minute-level H/D/Z/F geomagnetic components from fixed USGS observatories | one observatory-component time series | Adds ground magnetometer physical time series, not seismic, weather, or space-event metadata. | Exact API limits and component naming need a small bounded query window. |
| 3 | `argo_profile_ctd_f32` | subsurface ocean profiling | Argo float pressure, temperature, and salinity profile arrays | one float profile variable stream | Adds vertical ocean CTD structure, distinct from surface buoys, water-level stations, and wave spectra. | NetCDF parsing and stable profile URLs are the implementation cost. |
| 4 | `cod_crystal_structures_f32` | materials crystallography | unit-cell parameters and fractional atom coordinates from COD CIF files | one crystal structure coordinate/parameter stream | Adds inorganic/materials structure data, distinct from biomolecular PDB coordinates. | Need exact permissive COD IDs and a CIF parser that does not collapse tiny structures below the floor. |
| 5 | `cicids_network_flows_f64` | cybersecurity traffic telemetry | flow duration, packet counts, byte rates, and timing features | one CSV shard field stream | Adds operational network-flow behavior, distinct from vulnerability catalogs and OONI measurement metadata. | Source mirrors and licenses vary; avoid labels as primary and bound large CSVs. |
| 6 | `neuromorpho_swc_neuron_morphology_f32` | neuron morphology | SWC x/y/z/radius morphology coordinates | one neuron reconstruction | Adds biological branching geometry, distinct from cell-mask images and medical volumes. | Need stable SWC download URLs and enough non-tiny reconstructions. |
| 7 | `cwru_bearing_vibration_i16_or_f32` | rotating machinery diagnostics | bearing accelerometer vibration traces | one load/fault recording channel | Adds industrial vibration/acoustic condition-monitoring waveforms, distinct from motor feature tables. | MATLAB payload parsing and exact public file URLs need verification. |
| 8 | `tess_light_curve_flux_f32` | time-domain astronomy | TESS/Kepler flux and quality-filtered light-curve samples | one light-curve product field | Adds stellar/exoplanet time-series photometry, distinct from static Gaia astrometry and FITS image planes. | FITS table parsing and stable MAST product selection are the work. |
| 9 | `hrrr_model_forecast_fields_f32` | numerical weather prediction | selected HRRR model analysis/forecast fields from GRIB2 | one model variable grid | Adds model-generated physical fields rather than observations or remote-sensing images. | GRIB2 parsing is dependency-heavy; keep a tiny fixed subset. |
| 10 | `usda_fia_tree_measurements_f32` | forestry inventory | tree diameter, height, biomass, and plot measurement fields | one state/table field stream | Adds field-survey forestry structure, distinct from GBIF occurrences and land-cover rasters. | Public API/CSV pagination and table semantics need careful homogeneous field selection. |

## Recommended First Pass

`noaa_swpc_dscovr_solar_wind_f32` was the initial first pass, but three SWPC URL
families returned `404` during user-run download attempts. Keep it as a good
domain idea, but do not spend more retries on it without a verified product URL.

`cicids2017_network_flow_features_f64` was the next cybersecurity attempt, but
the direct CICIDS2017 URL returned a UNB HTML dataset page rather than the ZIP.
`kddcup99_network_intrusion_features_f64` also failed because the UCI KDD archive
returned `403`. Stop the cybersecurity branch until we have a verified mirror.

Use `magic_gamma_telescope_event_features_f64` as the current runnable fallback.
It has a small direct UCI archive data file and adds Cherenkov telescope event
image parameters, a different instrument/data-generating process from the
accepted astronomy catalog and FITS image recipes. A staging recipe has been
prepared at:

```bash
bash staging/magic_gamma_telescope_event_features_f64/download.sh
```

Use `usgs_geomag_observatory_minute_f32` after that if a stable source URL is
verified. Together, solar-wind and geomagnetism would still be a good
space-weather pair once DSCOVR URLs are known.

Use `argo_profile_ctd_f32` third. It is a stronger domain jump than more weather
or imagery, but it needs NetCDF tooling and more exact source-product selection.

## Avoid For This Round

- More Open-Meteo, NASA POWER, GHCN, CO-OPS, NDBC, or USGS NWIS variables unless
  the measurement process changes materially.
- More ordinary image or segmentation benchmarks unless the sensor/domain is
  genuinely new and license terms are clear.
- More catalog metadata counts from bibliographic, repository, museum, or API
  index sources unless the table itself is a distinct operational system.
- Raw compressed archive bytes; decode source-native numeric payloads instead.
