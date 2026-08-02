# VACV Core Segmentation MRC UInt16 — Preflight

This candidate is a native uint16 3D ground-truth segmentation volume from
Zenodo record `20262954`, *3D segmentation for VACV cores*, released under
CC BY 4.0.

The exact MRC file is 464×464×250 voxels (53,824,000 uint16 values and
107,649,024 total bytes). The preflight inspector validates the complete MRC
layout and reports label cardinality, histogram, spatial occupancy, transition
count, and repeated-slice statistics before the volume is considered for the
training corpus.

Run:

```bash
bash datasets/zenodo_vacv_core_segmentation_mrc_u16/download.sh
bash datasets/zenodo_vacv_core_segmentation_mrc_u16/inspect.sh
bash datasets/zenodo_vacv_core_segmentation_mrc_u16/build.sh
bash datasets/zenodo_vacv_core_segmentation_mrc_u16/verify.sh
```

The accepted representation is one natural 464×464×250 volume. Build removes
only the 1,024-byte MRC header and preserves all little-endian uint16 voxel
bytes unchanged. The mask contains values 0 and 255, with 2.64% foreground,
132 occupied slices, and 133 unique slice payloads.
