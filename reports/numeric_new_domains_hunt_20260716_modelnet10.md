# Numeric New-Domain Hunt: 3D CAD Mesh Geometry

Date: 2026-07-16

Goal: add a high-volume numeric source from a different data shape while keeping
downloads under the per-dataset 1 GB cap. No dataset acquisition was performed
for this review.

## Current Gap

The collection has rasters, waveforms, graph edge lists, tabular measurements,
biomolecular coordinates, LiDAR classifications, and glTF index buffers. It does
not yet have a large collection of native floating-point 3D object mesh vertex
coordinates from CAD-like shape models.

## Recommended Candidate

| rank | candidate id | new domain | primary target | natural sample | why it adds variety | acceptance guard |
|---:|---|---|---|---|---|---|
| 1 | `modelnet10_off_mesh_vertices_f32` | 3D CAD shape geometry | ModelNet10 OFF mesh vertex coordinates | one mesh's vertex coordinate array | Adds object-shape geometry as float32 coordinate arrays, distinct from rasters, graph edge lists, sparse matrices, biomolecular coordinates, and index-buffer streams. | Download defaults to 800 MB and is clamped to a hard 1 GB cap; verify requires at least 4,000 meshes, 3,000,000 coordinate values, and 12 MB primary output. |
| 2 | `neuromorpho_swc_neuron_morphology_f32` | neuron morphology | SWC reconstruction coordinates and radii | one reconstruction coordinate stream | Adds biological branching geometry beyond images and volumes. | Needs stable bulk URLs and enough non-tiny reconstructions. |
| 3 | `argo_profile_ctd_f32` | ocean profiling | Argo pressure, temperature, and salinity arrays | one profile-variable stream | Adds subsurface ocean CTD structure unlike surface buoy records. | NetCDF parsing and fixed product selection. |
| 4 | `openstreetmap_history_way_nodes_i64` | volunteered geographic editing history | OSM way node/reference sequences | one history shard field stream | Adds edit-history topology and references rather than current-state catalog tables. | Public history extracts can exceed the 1 GB cap, so needs careful regional selection. |

## First Pass

Start with ModelNet10:

```bash
bash staging/modelnet10_off_mesh_vertices_f32/download.sh
```

The build emits one float32 `[vertex, coordinate]` array per OFF mesh while
preserving source vertex order. It should fail rather than promote if the source
archive is incomplete or too small.

## Attempt Note

The first attempted URL, `https://modelnet.cs.princeton.edu/ModelNet10.zip`,
returned HTTP 404. The staging download script was updated to try the older
Princeton 3DShapeNets ModelNet10 archive path first while keeping the failed URL
as a later fallback.

## Acceptance Outcome

`modelnet10_off_mesh_vertices_f32` was downloaded by the user and then built
locally. The source ZIP was 473,402,300 bytes, below the 1 GB per-dataset
download cap. The archive contains 4,899 real OFF meshes after ignoring
`__MACOSX` resource-fork artifacts. Verification accepted 4,899 float32 primary
samples across 10 classes, with 139,741,776 total coordinate values and
558,967,104 primary sample bytes.
