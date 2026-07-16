# Numeric New-Domain Hunt: Maritime Vessel Movement

Date: 2026-07-16

Goal: add a high-volume numeric source from a domain not already represented,
with a hard per-dataset download cap of 1 GB. No dataset acquisition was
performed for this review.

## Current Gap

The collection has road-network graph topology, crash investigation tables,
aircraft states, bike trips, and transit schedules. It does not yet have
maritime vessel movement telemetry from AIS position reports.

## Recommended Candidate

| rank | candidate id | new domain | primary target | natural sample | why it adds variety | acceptance guard |
|---:|---|---|---|---|---|---|
| 1 | `noaa_marinecadastre_ais_2024_01_01_f32` | maritime vessel movement telemetry | NOAA MarineCadastre AIS CSV position/report fields for 2024-01-01 | one AIS numeric field stream | Adds vessel movement and vessel-state measurements, distinct from aircraft states, bike trips, road topology, crash records, weather, rasters, and market data. | Download defaults to 800 MB and is clamped to a hard 1 GB cap; verify requires at least 8 samples, 8,000,000 total values, and 32 MB primary output. |
| 2 | `neuromorpho_swc_neuron_morphology_f32` | neuron morphology | SWC reconstruction coordinates and radii | one reconstruction coordinate stream | Adds biological branching geometry beyond images and volumes. | Needs stable bulk URLs and enough non-tiny reconstructions. |
| 3 | `argo_profile_ctd_f32` | ocean profiling | Argo pressure, temperature, and salinity arrays | one profile-variable stream | Adds subsurface ocean CTD structure unlike surface buoy records. | NetCDF parsing and fixed product selection. |
| 4 | `openstreetmap_history_way_nodes_i64` | volunteered geographic editing history | OSM way node/reference sequences | one history shard field stream | Adds edit-history topology and references rather than current-state catalog tables. | Public history extracts can exceed the 1 GB cap, so needs careful regional selection. |

## First Pass

Start with a single daily AIS ZIP:

```bash
bash staging/noaa_marinecadastre_ais_2024_01_01_f32/download.sh
```

The build keeps numeric movement and vessel-state fields such as latitude,
longitude, speed over ground, course over ground, heading, vessel type, status,
length, width, draft, and cargo. It should fail rather than promote if the daily
file is too small or missing the expected schema.

## Acceptance Outcome

`noaa_marinecadastre_ais_2024_01_01_f32` was downloaded by the user and then
built locally. The source ZIP was 290,340,871 bytes, below the 1 GB
per-dataset download cap, and contained 7,296,275 AIS rows. Verification
accepted 11 float32 primary samples, with 74,224,797 total values and
296,899,188 primary sample bytes.
