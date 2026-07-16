# Numeric New-Domain Hunt: Road Network Graph Topology

Date: 2026-07-16

Goal: add a high-volume numeric source from a new data shape while keeping the
download below the per-dataset 1 GB cap. No dataset acquisition was performed
for this review.

## Current Gap

The collection has transport schedules, bike-trip coordinates, airport catalogs,
aircraft states, and FARS crash investigation tables. It does not yet have a
large road-network graph edge-list dataset where the native numeric material is
topological connectivity rather than observations or attributes.

## Recommended Candidate

| rank | candidate id | new domain | primary target | natural sample | why it adds variety | acceptance guard |
|---:|---|---|---|---|---|---|
| 1 | `snap_roadnet_edges_i32` | road infrastructure graph topology | SNAP roadNet-CA, roadNet-PA, and roadNet-TX edge endpoint lists | one state-endpoint column | Adds large native graph connectivity over road intersections/segments, distinct from tabular crash records, station/weather feeds, rasters, and market/order data. | Download defaults to 200 MB total and is clamped to a hard 1 GB cap; verify requires all three states, six samples, 10,000,000 total values, and 40 MB primary output. |
| 2 | `modelnet10_off_mesh_vertices_f32` | 3D CAD shape geometry | OFF mesh vertex coordinates | one mesh coordinate array | Adds object geometry beyond index buffers and rasters. | Source URL and license notes need verification. |
| 3 | `neuromorpho_swc_neuron_morphology_f32` | neuron morphology | SWC reconstruction coordinates and radii | one reconstruction coordinate stream | Adds biological branching geometry beyond images and volumes. | Needs stable bulk URLs and enough non-tiny reconstructions. |
| 4 | `argo_profile_ctd_f32` | ocean profiling | Argo pressure, temperature, and salinity arrays | one profile-variable stream | Adds subsurface ocean CTD structure unlike surface buoy records. | NetCDF parsing and fixed product selection. |

## First Pass

Start with the SNAP road networks:

```bash
bash staging/snap_roadnet_edges_i32/download.sh
```

The build emits signed 32-bit endpoint columns for each state road graph. It
should fail rather than promote if the graph files are incomplete or too small.

## Acceptance Outcome

`snap_roadnet_edges_i32` was downloaded by the user and then built locally. The
three source gzip files totaled 40,280,224 bytes, below the 1 GB per-dataset
download cap. Verification accepted 6 int32 primary samples across CA, PA, and
TX source/destination endpoint columns, with 24,920,660 total values and
99,682,640 primary sample bytes.
