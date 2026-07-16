# Numeric New-Domain Hunt: Forestry Field Inventory

Date: 2026-07-16

Goal: add a numeric series source from a different domain while enforcing enough
volume to justify inclusion. No dataset acquisition was performed for this
review.

## Current Gap

The accepted collection has biodiversity occurrences, land-cover rasters,
forest-adjacent hyperspectral staging attempts, and many weather/hydrology
sources. It does not yet have tree-level field inventory measurements collected
by forest survey crews.

## Recommended Candidate

| rank | candidate id | new domain | primary target | natural sample | why it adds variety | acceptance guard |
|---:|---|---|---|---|---|---|
| 1 | `usda_fia_ca_tree_measurements_f32` | forestry field inventory | California FIA TREE table measurement columns | one tree-table field stream | Adds field-measured tree diameter, height, stocking, biomass, carbon, and volume data, distinct from GBIF coordinates and land-cover rasters. | Build requires at least 20 float32 samples, 50,000 values per sample, and 1,000,000 total primary values. |
| 2 | `neuromorpho_swc_neuron_morphology_f32` | neuron morphology | SWC reconstruction coordinates and radii | one neuron reconstruction | Adds biological branching geometry beyond images and medical volumes. | Needs stable bulk URLs and enough non-tiny reconstructions. |
| 3 | `argo_profile_ctd_f32` | ocean profiling | Argo pressure, temperature, and salinity profiles | one float-profile variable stream | Adds subsurface ocean CTD structure unlike surface buoy records. | NetCDF parsing and fixed product selection. |
| 4 | `uci_combined_cycle_power_plant_f64` | thermal power-plant operation | ambient variables and electrical output | one table column | Adds thermodynamic plant-performance measurements. | Lower volume and XLSX parsing, so not first choice for this round. |

## First Pass

Start with the FIA California TREE table:

```bash
bash staging/usda_fia_ca_tree_measurements_f32/download.sh
```

The expected source is a state-level ZIP from the USDA FIA DataMart. The build
is intentionally stricter than recent compact UCI recipes; it should fail rather
than promote a tiny table. The download script also clamps the file-size limit
to a hard 1 GB maximum, with a lower 250 MB default.

## Acceptance Outcome

`usda_fia_ca_tree_measurements_f32` was downloaded by the user and then built
locally. The source ZIP was 67,691,301 bytes, below the 1 GB per-dataset
download cap. Verification accepted 43 float32 primary samples, with 13,318,757
total values and 53,275,028 primary sample bytes.
