# Numeric New Domains Hunt: Open Images Bounding-Box Annotations

## Recommendation

Stage `openimages_v6_train_bbox_annotations_f32`, using a deterministic byte-range prefix from the public Open Images V6 train bounding-box annotation CSV.

## Why This Adds New Territory

- Domain: computer-vision object-detection annotation geometry.
- Shape: millions of object-level annotation rows with normalized bounding-box coordinates and binary annotation-state flags.
- Difference from accepted datasets: the catalog has image pixels and segmentation label maps, but not large detection-annotation geometry streams.
- Numeric representation: source normalized decimal bbox coordinates and click coordinates are emitted as float32 streams; source `-1` missing-click sentinels are preserved; source `-1/0/1` annotation flags are emitted as signed int8 streams; image ids and label ids are excluded.

## Materiality

The full public train bounding-box CSV is about 2.25 GB, so the recipe uses an HTTP byte range and defaults to a 900 MB prefix. That keeps the dataset under the repository's 1 GB download cap while still yielding millions of complete annotation rows and over 90 MB of primary numeric binary data.

The recipe enforces:

- source download hard cap: 1,000,000,000 bytes
- default source byte range: 900,000,000 bytes
- complete-row floor: 3,000,000 rows
- verify sample floor: 8 retained numeric samples
- verify value floor: 60,000,000 values
- verify primary-byte floor: 180,000,000 bytes
- primary-output hard cap: 1,000,000,000 bytes

## Script To Run

```bash
bash staging/openimages_v6_train_bbox_annotations_f32/download.sh
```

After the download succeeds, build and verify locally:

```bash
bash staging/openimages_v6_train_bbox_annotations_f32/build.sh
bash staging/openimages_v6_train_bbox_annotations_f32/verify.sh
```

## Rejected Candidates In This Pass

- NOAA/NCEI Storm Events would have been a good severe-weather event telemetry source, but the endpoint was blocked from this environment during discovery.
- FEC campaign-finance bulk files would have added political-finance numeric records, but the official endpoint was also blocked during discovery.

## Acceptance Outcome

The Open Images V6 bounding-box annotation prefix downloaded, built, and verified successfully.

- source byte range: `0-899999999`
- source bytes: 900,000,000
- complete CSV rows: 5,821,816
- skipped partial tail rows: 1
- primary samples: 17
- skipped constant fields: `confidence_f32`
- primary values: 98,970,872
- primary bytes: 308,556,248
- coordinate range observed: -1.0 to 1.0, with -1.0 used by Open Images sentinels
