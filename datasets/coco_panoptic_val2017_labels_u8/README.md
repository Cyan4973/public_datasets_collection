# COCO Panoptic Validation Labels

This staged recipe collects COCO 2017 panoptic validation annotations and emits label-map samples, not photographs.

Primary outputs:

- `coco_panoptic_category_id_u8`: one raw `uint8` category-id grid per panoptic validation image.
- `coco_panoptic_segment_id_u32`: optional one raw `uint32` segment-id grid per image, enabled by default.

The default build uses a deterministic sorted prefix of validation annotations and caps primary output below the repository limit. Override knobs:

```sh
COCO_PANOPTIC_MAX_IMAGES=384
COCO_PANOPTIC_EMIT_SEGMENT_IDS=1
COCO_PANOPTIC_MAX_PRIMARY_BYTES=950000000
```

Usage after the user approves/runs the external download:

```sh
bash staging/coco_panoptic_val2017_labels_u8/download.sh
bash staging/coco_panoptic_val2017_labels_u8/build.sh
bash staging/coco_panoptic_val2017_labels_u8/verify.sh
```

Do not promote to `datasets/` until the current `download.sh`, `build.sh`, and `verify.sh` have succeeded locally.
