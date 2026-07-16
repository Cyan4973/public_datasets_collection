# Numeric New-Domain Hunt

Date: 2026-07-16

Goal: continue adding numeric series whose domain or measurement process is not
already well represented by the accepted collection. No dataset acquisition was
performed for this review.

## Latest Accepted Addition

`magic_gamma_telescope_event_features_f64` added Cherenkov telescope event-image
parameters from a small direct UCI file. That covered a new high-energy
astroparticle instrument domain and proved the old UCI direct-file path can be a
practical fallback when larger portal-style sources fail.

## Next Candidates

| rank | candidate id | new domain | primary target | natural sample | why it adds variety | main risk |
|---:|---|---|---|---|---|---|
| 1 | `uci_superconductivity_material_features_f64` | materials informatics / superconductors | numeric elemental composition descriptors and critical temperature from UCI Superconductivity `train.csv` | one source CSV numeric feature column | Adds condensed-matter/materials property data, distinct from biomolecular coordinates, protein properties, astronomy tables, and generic UCI sensor tables. | Direct ZIP URL may change; build must ignore formula strings and use only numeric `train.csv`. |
| 2 | `uci_combined_cycle_power_plant_f64` | thermal power-plant operation | ambient variables and electrical power output from CCPP | one source table column | Adds industrial thermodynamic plant performance data, different from household/load time series and power-grid matrices. | Source is XLSX inside ZIP, requiring simple local XML parsing. |
| 3 | `uci_concrete_compressive_strength_f64` | civil engineering materials testing | concrete mix component quantities and compressive strength | one source table column | Adds engineered-material mixture design and strength measurements. | Source is legacy Excel; parser/tooling may be more fragile than CSV/ZIP. |
| 4 | `usgs_geomag_observatory_minute_f32` | geomagnetic observatory physics | H/D/Z/F minute-level magnetic components | one observatory-component time series | Adds ground magnetometer time series, not weather, seismic, or space-event metadata. | Needs verified USGS endpoint parameters. |
| 5 | `neuromorpho_swc_neuron_morphology_f32` | neuron morphology | SWC x/y/z/radius reconstruction coordinates | one neuron reconstruction | Adds branching biological geometry beyond images and medical volumes. | Requires stable bulk/download URLs and enough non-tiny reconstructions. |

## Recommended First Pass

Start with `uci_superconductivity_material_features_f64`:

```bash
bash staging/uci_superconductivity_material_features_f64/download.sh
```

The expected source is a small UCI ZIP with `train.csv`. It should produce many
medium-sized float64 samples while staying well below the 1 GB primary-output
cap.

## Acceptance Outcome

`uci_superconductivity_material_features_f64` was downloaded by the user and
then built locally. Verification accepted 82 float64 primary samples, one per
numeric `train.csv` field, with 1,743,566 total values and 13,948,528 primary
sample bytes.
