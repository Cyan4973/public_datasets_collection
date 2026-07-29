# TUM RGB-D ground-truth poses — float64

This recipe extracts the motion-capture ground-truth trajectory from the TUM
RGB-D `freiburg1_xyz` sequence. It preserves the source pose geometry as two
row-major float64 matrices:

- translation: `3000 × 3` (`tx`, `ty`, `tz`) in metres
- orientation: `3000 × 4` (`qx`, `qy`, `qz`, `qw`) as unit quaternions

The timestamp column is used only to validate strict trajectory order. It is
not emitted as primary compression material.

The benchmark publishes pose ordinates as decimal numeric fields. They are
parsed directly into IEEE-754 float64; there is no narrower binary source field
being widened. Independent verification reparses the archive and compares all
21,000 emitted values.

Source: <https://cvg.cit.tum.de/data/datasets/rgbd-dataset>

License: CC BY 4.0. Cite J. Sturm et al., “A Benchmark for the Evaluation of
RGB-D SLAM Systems,” IROS 2012.

## Run

```bash
bash datasets/tum_rgbd_groundtruth_pose_f64/download.sh
bash datasets/tum_rgbd_groundtruth_pose_f64/build.sh
bash datasets/tum_rgbd_groundtruth_pose_f64/verify.sh
```

If the accepted TUM depth recipe's exact archive is already cached, the
downloader validates and hard-links it instead of downloading another 448 MB.
