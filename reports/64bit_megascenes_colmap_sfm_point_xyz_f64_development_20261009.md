# MegaScenes COLMAP SfM point float64 development

## Outcome

Accepted `megascenes_colmap_sfm_point_xyz_f64`, built from the COLMAP sparse reconstructions in MegaScenes v1.0 (Cornell; Tung et al., ECCV 2024).

This is the corpus's first photogrammetric structure-from-motion material. The points are sparse, bundle-adjusted triangulations, each model is in its own arbitrary similarity frame, and records come in COLMAP hash order. The 3-D point-coordinate modality itself already exists: OSIRIS-REx OLA lidar xyz f64, VLS-128 and Velodyne lidar xyz, ModelNet mesh vertices, and downstream rMD17 coordinates and TUM poses. The family is therefore labelled `new_source`, not `new_modality`. Measured breadth is OK for both primary series.

## Source and rights

- Source: AWS Open Data bucket `s3://megascenes`, read anonymously over HTTPS at `https://megascenes.s3.us-west-2.amazonaws.com/`.
- Scope: every `reconstruct/000/<sss>/colmap/<k>/points3D.bin` (scene IDs 000000-000999), 391 objects, 445,121,839 bytes. The objects were last modified 2024-05-30 to 2024-07-19.
- Pinning: `sources.tsv` records key, size, MD5 (single-part ETag) and last-modified for each object. The listing was taken 2026-10-09 and `discover.sh` records how.
- License: CC BY 4.0. The MegaScenes datasheet says: "This dataset is licensed under the Creative Commons Attribution 4.0 International License. The photos in the dataset have their own licenses." The awslabs open-data-registry `megascenes.yaml` gives the same license. Only the authors' reconstruction outputs are used; no photos are fetched.

## Shape and conversion

Each natural record is one COLMAP reconstruction model, and one model gives one sample per series. Decoding is a pure-stdlib struct parse:

- a uint64 point count;
- then, per point, `<QdddBBBdQ` (id, x, y, z, r, g, b, error, track_length; 51 bytes);
- then track_length × (uint32 image_id, uint32 point2D_idx), which is skipped.

The parse must end exactly at EOF. Coordinates must be finite, errors must be finite and non-negative, and point IDs must be unique. Values are copied bit-exactly as little-endian float64 in file order. Point IDs, RGB and track arrays are not emitted, and images.bin keypoints (float32 SIFT locations widened to double) are not used. The 43 models with fewer than 334 points (under 1,002 XYZ values; largest dropped model 325 points) are excluded and listed in `filtered/<id>/ingest_stats.json`. Large models are kept whole.

| series | role | content |
| --- | --- | --- |
| `sfm_point_xyz_f64` | primary | x,y,z per point, interleaved, model frame |
| `sfm_point_reproj_error_f64` | primary | per-point mean reprojection error, pixels |

## Accepted output

- Source files validated: 391 (445,121,839 bytes); models kept: 348; points: 4,370,514; track entries: 27,734,566
- `sfm_point_xyz_f64`: 348 samples, 13,111,542 values, 104,892,336 bytes. Samples range from 1,026 to 1,168,218 values, median 11,490.
- `sfm_point_reproj_error_f64`: 348 samples, 4,370,514 values, 34,964,112 bytes. Median sample 3,830 values; values range from 4.1e-8 to 3.97 px.
- Total primary: 696 samples, 17,482,056 values, 139,856,448 bytes.
- Breadth (zlsim): xyz is nearest to `mace_mp_foundation_model_weights_f64` at 0.0751, and error is nearest to downstream `msd_timbre_cov` at 0.1062. Verdict OK.

## Judge checks

- `gate.py` PASS with no warnings. I ran `verify.sh` myself and it passed, with every count matching the manifest.
- Independent decode: a raw-offset slicer of my own reproduced the xyz and error bytes of 13 samples exactly (12 random plus the largest, 389,406 points). This makes up for `verify` reusing the build's `derive()` in compare mode.
- Live S3 re-listing (2 pages): the 391 points3D.bin keys are identical to `sources.tsv`. The bucket has about 460 reconstruct/ prefixes, so prefix 000 is a bounded coherent subset.
- Bytes:
  - Full float64 mantissas in both series (no value has 29 or more trailing zero bits), so nothing is widened.
  - Per-model extents run from 0.57 to 362 (median 30), as expected from the SfM gauge.
  - Consecutive points are about 0.8 to 0.98 as far apart as random pairs, which fits hash order.
  - The error ceiling just under 4 px matches COLMAP's default reprojection-error filter.
- Duplicates:
  - About 2.6% of points exactly repeat an earlier point's xyz and error with a different track. This is a source property, most likely duplicate Commons photos.
  - No xyz triple and no error value is shared between any two samples, so there are no near-duplicate models or scenes.
- Rights: I read the datasheet license line and the AWS registry entry myself. There are no credentials (the only 'token' strings are S3 continuation tokens in documentation-only `discover.sh`), and no personal data is emitted.
- Novelty: `novelty.py` matches nothing outside this staging recipe, apart from an unrelated photogrammetry normal-map raster family. Breadth keys return 0/0/0.
