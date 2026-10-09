# apple_hypersim_normal_cam_f16

Camera-space surface-normal G-buffers (`normal_cam`) from Apple's
[Hypersim](https://github.com/apple/ml-hypersim) photorealistic synthetic
indoor-scene dataset. Each sample is one rendered frame stored as native IEEE
binary16, `[768, 1024, 3]` (row, column, xyz component), 4,718,592 bytes.
200 frames are selected, one for each of 200 evenly spaced public scenes
covering all 51 Evermotion Archinteriors volumes in the release. 198 are
emitted (934,281,216 bytes); two degenerate frames are dropped (see below).

## License and attribution

The Hypersim Dataset is licensed under the Creative Commons
Attribution-ShareAlike 3.0 Unported License (README of apple/ml-hypersim at
commit `3463c5c4a75f3cbfc65ed31cfd6e87204b3a2254`; `download.sh` re-checks
this sentence). Credit: Roberts et al., *Hypersim: A Photorealistic Synthetic
Dataset for Holistic Indoor Scene Understanding*, ICCV 2021
(arXiv:2011.02523), Apple Inc. Share-alike: any redistribution of these
samples or of anything adapted from them must use CC BY-SA 3.0. The
repository's `LICENSE.txt` is Apple's sample-code license, which covers code
only. No upstream code is used.

## Acquisition (range requests only)

Each scene is a single zip of 1.0 to 15.8 GB in which every member is stored
uncompressed. 68 of the selected zips are larger than 4 GiB and use zip64
records. For each selected scene, `download.sh`:

1. fetches the last 128 KiB of the zip, then parses the EOCD and, when
   present, the zip64 locator and EOCD record to find the central directory;
2. fetches the central directory (0.4 to 3 MB) and looks up the target
   member's local-header offset, size and CRC-32;
3. fetches the local header plus the member (0.5 to 2.2 MB, with 1 KiB of
   slack), checks that the local-header name matches, checks the CRC-32, and
   fully decodes the HDF5;
4. keeps only the member and a JSON sidecar (offsets, CRC, sha256). It
   deletes the tail, central-directory and slab scratch files.

Expected kept download is about 0.2 GB, from about 0.4 GB transferred. The
split CSV and README are fetched at the pinned commit and checked against
their sha256 values.

## Selection

`scripts/selection.py` reads the pinned `metadata_images_split_scene_v1.csv`:

- Public scenes are the scenes that have `included_in_public_release == True`
  rows: 457 scenes, the same list as the 457 zips in the upstream
  `contrib/99991/download.py`.
- Scenes are sorted by name, and the scene at index `k*457//200` is taken for
  k = 0..199.
- The camera is `cam_00`. If a scene has no public `cam_00`, the
  lowest-numbered camera with public frames is used. Three scenes fall back
  to `cam_01`: ai_011_003, ai_044_003 and ai_054_002.
- The frame is the median (element `len//2`) of that camera's sorted public
  frame ids. Excluded frames are never chosen, and those frames are also
  missing from the zips.

The limit of 200 scenes is set by the size cap: one frame is 4.72 MB, so all
457 scenes would be about 2.16 GB, over the 1 GB limit on primary output.
`discover.sh` regenerates `sources.tsv` and pins each zip's Content-Length
and Last-Modified through HEAD requests.

## Decode

`scripts/hypersim_h5.py` is adapted from the accepted
`bosch_cnc_milling_ciss_vibration_i16` reader, with binary16 support and
rank-generic chunk assembly added. It reads superblock v0, the symbol-table
root group and v1 object headers, then a chunked layout v3 with a v1 B-tree.
The real files use 96x128x1 chunks, deflate level 9 and no shuffle, giving
192 chunks per frame. The complete chunk grid is required. Anything outside
this scope is rejected.

`scripts/selftest.py`, which runs at the start of `build.sh`, checks the
reader and the zip helper on synthetic files:

- HDF5: edge chunks in every dimension, multi-level B-trees, continuation
  messages, shuffle, and filter masks.
- Rejection cases: fletcher32, big-endian data, integer types, missing
  chunks, and a wrong dataset name.
- Zip: plain archives, a zip64 EOCD archive with more than 65,535 entries,
  and zip64 extra-field offsets above 4 GiB. Renamed or corrupted members
  must be rejected.

While authoring, the decode of `ai_001_001` frame 49 was also compared with
the scene's own `normal_cam.png` preview. The preview equals
`(n+1)/2*255` to within 0 or 1 on every sampled pixel, which independently
confirms the chunk order and axis order.

## Values and missing-value policy

Words are emitted bit-exact, with no renormalization, clipping or NaN
replacement. Most pixels are unit vectors. Pixels on geometric edges are
filtered and so are not unit length. In some scenes the reconstruction
filter overshoots; the realized range is -5.64..4.64 (`ai_054_005`). Pixels
with no geometry hit (views through windows into empty space) are stored
upstream as the quiet NaN `0x7e00` in all three components. They are kept
bit-exact and counted per sample: 65 of 198 frames contain NaN, 0.88% of all
values, worst frame `ai_004_010` at 19.5%. No Inf occurs.

`build.py` and `verify.py` fail on any of the following:

- a finite magnitude above 8;
- fewer than 50% finite pixels;
- fewer than 50% of pixels within 0.01 of unit norm.

A frame is dropped and recorded in `filtered/<id>/build_stats.json` when one
pixel triplet covers more than 90% of it or it has fewer than 256 distinct
words. `verify.py` re-derives this drop set on its own. Realized drops:
`ai_003_001` (14 distinct words, a few flat planes) and `ai_039_003` (a wall
covering 97% of the view). Frames whose most common triplet covers more than
50% (30 of 198) are listed in `build_stats.json` but kept.

## Verify

`verify.py`:

- re-derives the selection from the CSV;
- re-checks the member identities;
- re-decodes every member and requires the result to be byte-identical to
  the sample;
- recomputes every statistic using an independent bit-level binary16
  conversion, which is cross-checked against `struct`'s `'e'` codec for all
  65,536 words;
- enforces the policy above;
- checks that the index fields are correct, that there are no duplicates,
  stray files or constant samples, and that the floors, the 1 GB cap and the
  manifest's sample count and total size all hold.
