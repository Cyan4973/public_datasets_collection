# Numeric New-Domain Hunt: Manufacturing Defect Features

Date: 2026-07-16

Goal: continue adding numeric series from domains not already represented by the
accepted collection. No dataset acquisition was performed for this review.

## Current Gap

The accepted collection has industrial-adjacent data from sensorless drive
diagnosis, gas sensors, energy systems, and power-grid cases, but it does not
yet have a compact manufacturing quality-control table built from defect-region
measurements on produced material.

## Recommended Candidate

| rank | candidate id | new domain | primary target | natural sample | why it adds variety | main risk |
|---:|---|---|---|---|---|---|
| 1 | `uci_steel_plates_faults_features_f64` | manufacturing surface-defect inspection | 27 numeric geometric, luminosity, material, and index features from UCI Steel Plates Faults | one source feature column | Adds industrial quality-control measurements from steel-plate fault regions, distinct from sensor waveforms, images, weather, finance, and catalog metadata. | UCI legacy direct-file path may change; build must exclude the seven class-label columns. |
| 2 | `uci_combined_cycle_power_plant_f64` | thermal power-plant operation | ambient operating variables and electrical output | one source table column | Adds thermodynamic plant-performance measurements. | XLSX parsing needed. |
| 3 | `usda_fia_tree_measurements_f32` | forestry field inventory | tree diameter, height, biomass, and plot measurement fields | one table field stream | Adds field-survey forest structure. | FIA direct ZIP paths and table sizes need careful state selection. |
| 4 | `neuromorpho_swc_neuron_morphology_f32` | neuron morphology | SWC x/y/z/radius reconstruction coordinates | one neuron reconstruction | Adds biological branching geometry beyond images and volumes. | Stable bulk URLs and enough non-tiny reconstructions. |

## First Pass

Start with the steel-plate fault features because the source is a small direct
UCI numeric file and the class-label columns can be cleanly excluded:

```bash
bash staging/uci_steel_plates_faults_features_f64/download.sh
```

If the download succeeds, the build should emit 27 float64 samples, one for
each non-label source feature.

## Acceptance Outcome

`uci_steel_plates_faults_features_f64` was downloaded by the user and then
built locally. Verification accepted 27 float64 primary samples, with 52,407
total values and 419,256 primary sample bytes.
