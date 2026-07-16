# SNAP Road Network Edge Endpoints Int32

Candidate recipe for road-infrastructure graph topology from the SNAP road
network datasets.

The target sources are gzipped edge lists for California, Pennsylvania, and
Texas. Natural samples are one edge endpoint column per state: source node IDs
and target node IDs preserving source edge order. Comment lines and metadata
headers are not emitted.

Run:

```bash
bash staging/snap_roadnet_edges_i32/download.sh
```

Then build and verify locally:

```bash
bash staging/snap_roadnet_edges_i32/build.sh
bash staging/snap_roadnet_edges_i32/verify.sh
```
