# TUM RGB-D Pose Float64 Development — 2026-07-28

`tum_rgbd_groundtruth_pose_f64` adds a new 64-bit sample geometry to the
corpus: ordered rigid-body poses. The source domain overlaps the accepted TUM
depth-camera recipe, but the primary material does not. It consists of a
translation trajectory and an orientation trajectory rather than image
rasters.

The candidate was grounded against committed `datasets/*/manifest.toml`,
`attempts/dataset_status.tsv`, and `reports/accepted_recipe_audit.tsv`. The
existing local archive was inspected only after identifying the exact accepted
TUM recipe and stable source archive.

## Representation

The official `freiburg1_xyz` archive publishes `groundtruth.txt` as an ordered
numeric table:

`timestamp tx ty tz qx qy qz qw`

The timestamp is used to require strict trajectory order but is not emitted as
primary material. Published decimal pose ordinates are parsed directly as
IEEE-754 float64; no narrower binary field is widened. The output preserves
the pose structure as two row-major samples:

- translation matrix: `3000 × 3`, XYZ in metres
- orientation matrix: `3000 × 4`, XYZW unit-quaternion components

Every source row is required, finite, and strictly time ordered. Quaternion
norms must remain within `0.001` of unity; values are not renormalized.

## Realized output

Local reuse validated the exact `448,204,271`-byte source archive with SHA-256
`a0236d97b8c30cd93b653656d2b6c293ff7c982a4130ef2a1a8beecdb124ef98`.
Build and independent source-to-output verification passed:

- poses: `3,000`
- trajectory duration: `30.0896` seconds
- primary samples: `2`
- primary values: `21,000`
- primary bytes: `168,000`
- median sample: `10,500` values
- median translation step: `0.0033076` metres
- median adjacent quaternion absolute dot product: `0.9999998`

The streams are strongly structured rather than noise-like. Preliminary raw
zlib ratios were `0.3413` for translation and `0.3113` for orientation.
Independent verification reparses the archive and compares all 21,000 float64
values and both matrix shapes.
