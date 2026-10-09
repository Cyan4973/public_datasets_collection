# MegaScenes COLMAP SfM Bundle-Adjusted 3-D Points (float64)

Source: MegaScenes v1.0 (Cornell; Tung et al., ECCV 2024), hosted in the AWS
Open Data bucket `s3://megascenes` (us-west-2) and read anonymously over HTTPS.
License: CC BY 4.0 (MegaScenes datasheet; AWS Open Data Registry entry). The
photos carry their own licenses and are not used.

## Scope

Every `reconstruct/000/<sss>/colmap/<k>/points3D.bin` object, i.e. all COLMAP
sparse reconstruction models for scene IDs 000000-000999: 391 files, 445,121,839
bytes (listing pinned 2026-10-09 in `sources.tsv`; `discover.sh` documents how).
Size distribution is heavy-tailed (p50 ~255 KB, largest 48 MB); every model is
kept whole as one sample. Models with fewer than 334 points (fewer than 1,002
XYZ values) are dropped and listed in `filtered/<id>/ingest_stats.json`.

Realized build (2026-10-09): 391 sources parsed exactly to EOF; 348 models kept,
43 dropped as small (largest dropped model 325 points); 4,370,514 points.

| series | samples | values | bytes |
| --- | --- | --- | --- |
| `sfm_point_xyz_f64` | 348 | 13,111,542 | 104,892,336 |
| `sfm_point_reproj_error_f64` | 348 | 4,370,514 | 34,964,112 |

XYZ sample sizes range from 8.2 KB to 9.3 MB (median 11,490 values). Errors
range from 4e-8 to 3.97 px.

## Series

| series | role | content |
| --- | --- | --- |
| `sfm_point_xyz_f64` | primary | x,y,z float64 per point, interleaved, file order |
| `sfm_point_reproj_error_f64` | primary | per-point mean reprojection error (pixels), float64, file order |

Both are native float64 fields of COLMAP's points3D.bin, copied bit-exactly.
Point IDs, RGB and the track arrays (image_id, point2D_idx) are not emitted.
images.bin keypoints are not used (they are float32 SIFT locations widened to
double).

## Format

`points3D.bin`: uint64 `num_points`, then per point
`<Q ddd BBB d Q>` (id, x, y, z, r, g, b, error, track_length, 51 bytes) followed
by `track_length * <II>` (image_id, point2D_idx). The parser requires the parse
to end exactly at EOF, finite coordinates, finite non-negative errors and unique
point IDs. Record order is COLMAP's write order (hash-map order, not sorted by
ID or space).

## Scripts

- `download.sh`: curl each pinned key (resumable), check size, MD5 (= S3 ETag)
  and a full parse.
- `build.sh`: emits `samples/<id>/<series>/<sss>_<sss>_model<k>.bin`, the index
  and `filtered/<id>/ingest_stats.json`.
- `verify.sh`: re-parses all sources, re-derives sample hashes, index and stats,
  and checks the manifest counts.
- `scripts/megascenes_points3d.py selftest`: synthetic round-trip of the parser.
