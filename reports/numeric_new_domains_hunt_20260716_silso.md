# Numeric New-Domain Hunt: Solar Activity Indices

Date: 2026-07-16

Goal: continue adding numeric series from domains not already represented by the
accepted collection. No dataset acquisition was performed for this review.

## Current Gap

The collection has space and astronomy coverage from Gaia, MAGIC telescope event
features, GWOSC strain, FITS image planes, PDS rasters/radargrams, and NASA
DONKI event metadata. It does not yet have a long-running solar-observatory
activity index with daily/monthly physical measurements.

## Recommended Candidate

| rank | candidate id | new domain | primary target | natural sample | why it adds variety | main risk |
|---:|---|---|---|---|---|---|
| 1 | `silso_sunspot_activity_indices_f32` | solar activity / heliophysics | SILSO daily and monthly total sunspot-number CSV indices | one cadence-field time series | Adds centuries-scale solar-observatory index data, distinct from event catalogs, terrestrial weather, astronomy catalogs, and image/raster payloads. | SILSO endpoint names may change; validation should catch HTML/error pages and schema drift. |
| 2 | `usgs_geomag_observatory_minute_f32` | geomagnetic observatory physics | minute-level magnetic field components | one observatory-component time series | Adds ground magnetometer physical time series. | USGS endpoint parameters still need verification. |
| 3 | `argo_profile_ctd_f32` | subsurface ocean profiling | Argo pressure, temperature, and salinity profiles | one float-profile variable stream | Adds vertical ocean CTD structure, unlike surface buoy or coastal water-level records. | NetCDF parsing and fixed product selection. |
| 4 | `neuromorpho_swc_neuron_morphology_f32` | neuron morphology | SWC x/y/z/radius reconstruction coordinates | one neuron reconstruction | Adds biological branching geometry beyond images and volumes. | Stable bulk URLs and enough non-tiny reconstructions. |

## First Pass

Start with SILSO because it is compact, direct CSV, and has a distinct
measurement process:

```bash
bash staging/silso_sunspot_activity_indices_f32/download.sh
```

If the download succeeds, the build should emit six float32 samples: daily and
monthly sunspot number, standard deviation, and observation count.

## Acceptance Outcome

`silso_sunspot_activity_indices_f32` was downloaded by the user and then built
locally. Verification accepted 6 float32 primary samples, with 230,296 total
values and 921,184 primary sample bytes.
