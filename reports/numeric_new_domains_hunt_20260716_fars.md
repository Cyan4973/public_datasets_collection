# Numeric New-Domain Hunt: Traffic Fatality Investigation Tables

Date: 2026-07-16

Goal: add a high-volume numeric source from a domain not already represented,
with an explicit per-dataset download cap below 1 GB. No dataset acquisition was
performed for this review.

## Current Gap

The accepted collection has road-adjacent mobility data such as Citi Bike trips,
airport catalogs, OpenSky aircraft states, and sports telemetry. It does not yet
have official crash investigation tables with person, vehicle, roadway,
environment, and crash-event variables.

## Recommended Candidate

| rank | candidate id | new domain | primary target | natural sample | why it adds variety | acceptance guard |
|---:|---|---|---|---|---|---|
| 1 | `nhtsa_fars_2022_crash_tables_f64` | traffic safety / crash investigation | NHTSA FARS 2022 ACCIDENT, PERSON, and VEHICLE CSV tables | one table-field numeric series | Adds official fatal-crash investigation variables, distinct from transport schedules, bike trips, aircraft positions, weather feeds, and catalog metadata. | Download defaults to 250 MB and is clamped to a hard 1 GB cap; verify requires at least 40 samples, 2,000,000 total values, and 16 MB primary output. |
| 2 | `neuromorpho_swc_neuron_morphology_f32` | neuron morphology | SWC reconstruction coordinates and radii | one reconstruction coordinate stream | Adds biological branching geometry beyond images and volumes. | Needs stable bulk URLs and enough non-tiny reconstructions. |
| 3 | `argo_profile_ctd_f32` | ocean profiling | Argo pressure, temperature, and salinity arrays | one profile-variable stream | Adds subsurface ocean CTD structure unlike surface buoy records. | NetCDF parsing and fixed product selection. |
| 4 | `modelnet10_off_mesh_vertices_f32` | 3D CAD shape geometry | OFF mesh vertex coordinate streams | one mesh coordinate array | Adds CAD object geometry beyond index buffers and rasters. | Source URL and license notes need verification. |

## First Pass

Start with the FARS 2022 national CSV ZIP:

```bash
bash staging/nhtsa_fars_2022_crash_tables_f64/download.sh
```

The build dynamically keeps numeric, non-ID fields from ACCIDENT, PERSON, and
VEHICLE tables only if they have enough values and are non-constant. It should
fail rather than promote a tiny extraction.

## Acceptance Outcome

`nhtsa_fars_2022_crash_tables_f64` was downloaded by the user and then built
locally. The source ZIP was 34,689,724 bytes, below the 1 GB per-dataset
download cap. Verification accepted 190 float64 primary samples across
ACCIDENT, PERSON, and VEHICLE tables, with 12,662,622 total values and
101,300,976 primary sample bytes.
