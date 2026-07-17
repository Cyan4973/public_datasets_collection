# Open Images V6 Train Bounding-Box Annotation Geometry

This staging recipe collects a bounded byte-range prefix from the public Open Images V6 train bounding-box annotation CSV and emits numeric annotation geometry and flag fields.

The domain is computer-vision object-detection annotation geometry. The recipe does not download images. It excludes image ids, label ids, and other text fields from primary samples, retaining only numeric bounding-box coordinates and annotation flags:

- `xmin`, `xmax`, `ymin`, `ymax`, and the eight `xclick*` click-coordinate fields as little-endian float32 streams; click fields preserve Open Images `-1` missing-click sentinels
- `is_occluded`, `is_truncated`, `is_group_of`, `is_depiction`, `is_inside` as signed int8 streams preserving Open Images `-1/0/1` values

Run:

```bash
bash staging/openimages_v6_train_bbox_annotations_f32/download.sh
bash staging/openimages_v6_train_bbox_annotations_f32/build.sh
bash staging/openimages_v6_train_bbox_annotations_f32/verify.sh
```

The source CSV is larger than 1 GB, so the download script requests a deterministic byte range and refuses any response above the configured cap. The build skips only the final incomplete CSV row if the byte range cuts through a line.
