# Zenodo TrackML Event Truth Float32

This candidate targets the reduced TrackML collision-event dataset published
with the TrackFormers research artifact on Zenodo record `14386134`. The
natural sample is one simulated detector event. The deposited schema provides
the following row-aligned float payload:

`[x, y, z, vx, vy, vz, px, py, pz, weight]`

These are the measured three-dimensional hit position, true production vertex,
true particle momentum, and per-hit reconstruction weight. Integer detector
volume, charge, particle ID, and event ID fields are used only for structural
validation and are not mixed into the float32 payload.

This is not another flat particle-physics feature table. Existing SUSY and
Cherenkov-event families contain one short row per independent event. TrackML
instead contains a variable-size matrix inside each collision event, preserving
the many detector hits produced by intertwined charged-particle tracks. It is
also unlike a static mesh vertex cloud: rows carry coupled position, momentum,
and reconstruction-weight fields generated within a layered tracking detector.

The original TrackML citation record is no longer available through Zenodo's
record API, and CERN Open Data does not catalogue it. Metadata discovery found
this newer, explicit CC BY 4.0 dataset instead. It contains two reduced TrackML
archives and three REDVID simulation datasets. The selected bounded archive is
`trackml_40k-events-10-to-50-tracks.tar.gz` (134,638,012 bytes); the larger
200-to-500-track archive exceeds the repository's source-size cap.

Run from the repository root:

```bash
bash staging/zenodo_trackml_event_truth_f32/discover.sh
```

Results are written beneath `.data/discovery/zenodo_trackml_event_truth_f32/`.
After successful discovery, download and inventory the exact bounded archive:

```bash
bash staging/zenodo_trackml_event_truth_f32/download.sh
```

The preflight records every safe regular member, extracts only small embedded
README or metadata files for inspection, and reports representative file
signatures.

The archive preflight found one 1.203 GB CSV with columns for measured hit
position, detector volume, production vertex, particle momentum, charge,
particle ID, hit weight, and event ID. Profile its complete contents with:

```bash
bash staging/zenodo_trackml_event_truth_f32/profile.sh
```

The profiler streams directly from the compressed tar archive and does not
materialize the source CSV.

The complete profile found 43,725 event blocks and 9,949,945 hit rows. The
source repeats many events under consecutive event IDs: only 19,558 float
payloads are unique. Exact duplicates are removed, leaving 51,052,080 float32
values and 204,208,320 bytes. The unique natural samples have a median of 2,350
values, so the family passes the sample-size floor without concatenation.

Build and verify the unique events with:

```bash
bash staging/zenodo_trackml_event_truth_f32/build.sh
bash staging/zenodo_trackml_event_truth_f32/verify.sh
```
