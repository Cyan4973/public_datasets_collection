# Numeric New-Domain Hunt: Molecular Property Tables

Date: 2026-07-16

Goal: add a high-volume numeric source from a different domain while keeping
downloads under the per-dataset 1 GB cap. No dataset acquisition was performed
for this review.

## Current Gap

The accepted collection has protein sizes, reaction catalogs, biomolecular
coordinates, and sequence-derived numeric payloads. It does not yet have a large
small-molecule medicinal-chemistry property table with native physicochemical
descriptors across many compounds.

## Recommended Candidate

| rank | candidate id | new domain | primary target | natural sample | why it adds variety | acceptance guard |
|---:|---|---|---|---|---|---|
| 1 | `chembl_molecule_properties` | medicinal chemistry / drug discovery | ChEMBL calculated molecule properties | one property family across molecules | Adds molecular weight, ALogP, polar surface area, QED, H-bond counts, rotatable bonds, rings, and heavy-atom counts from small-molecule records. | Download defaults to 900 MB and is clamped to a hard 1 GB cap; verify requires at least 1,000,000 values per family. |
| 2 | `neuromorpho_swc_neuron_morphology_f32` | neuron morphology | SWC reconstruction coordinates and radii | one reconstruction coordinate stream | Adds biological branching geometry beyond images and volumes. | Needs stable bulk URLs and enough non-tiny reconstructions. |
| 3 | `argo_profile_ctd_f32` | ocean profiling | Argo pressure, temperature, and salinity profile arrays | one profile-variable stream | Adds subsurface ocean CTD structure unlike surface buoy records. | NetCDF parsing and fixed product selection. |
| 4 | `modelnet10_off_mesh_vertices_f32` | 3D CAD shape geometry | OFF mesh vertex coordinate streams | one mesh vertex-coordinate array | Adds CAD object geometry beyond index buffers and rasters. | ModelNet direct URL and license notes need verification. |

## First Pass

Start with the ChEMBL molecule properties staging recipe:

```bash
bash staging/chembl_molecule_properties/download.sh
```

This is intentionally a larger candidate than the recent compact UCI tables. It
should download cursor-paginated projected JSON pages under the hard 1 GB cap
and then build nine large numeric families.

## Attempt Outcome

The first ChEMBL page downloaded and validated, but the API-provided
`page_meta.next` URL for page 1 returned repeated HTTP 500 responses. Do not
retry this candidate without a different ChEMBL extraction path.
