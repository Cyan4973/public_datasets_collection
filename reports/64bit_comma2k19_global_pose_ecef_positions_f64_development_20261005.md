# comma2k19 global-pose ECEF camera positions float64 development

## Outcome

Accepted `comma2k19_global_pose_ecef_positions_f64`. Each sample is one
comma2k19 one-minute segment's published `global_pose/frame_positions` array:
the Earth-centred, Earth-fixed position of the road-facing camera, in metres,
one row per 20 Hz video frame. comma.ai computed the poses with its tightly
coupled INS/GNSS/vision optimizer on Laika-processed raw GNSS.

This is a new source and a new quantity for the corpus: a geodetic vehicle
trajectory from a fused state estimator. The nearest accepted families are
`tum_rgbd_groundtruth_pose_f64` (indoor motion-capture pose in a local frame),
`noaa_cors_rinex_observations_f64` (raw GNSS observables, not solved
positions), `noaa_marinecadastre_ais_2024_01_01_f32` (vessel lat/lon float32
columns at irregular report times) and the HSL GTFS static shape polylines.
The modality, coordinate trajectories, is already known.

## Source and rights

- Source: official `commaai/comma2k19` Hugging Face dataset repository,
  pinned to commit `4bff77c7254c654c28d4c2726186b4e825adccee`.
- Archives: `raw_data/Chunk_1.zip` … `Chunk_10.zip`, ZIP64, 8,731,252,405 to
  9,901,342,289 bytes each (94.6 GB in total). Archive identity is checked per
  chunk via the resolve headers `x-repo-commit`, `x-linked-size` and
  `x-linked-etag` (LFS SHA-256, pinned in `chunks.tsv`).
- Only about 58.6 MB is fetched: each chunk's 4 KiB tail, its central
  directory (1.7–2.0 MB, SHA-256 pinned), and the 2,035 exact member byte
  ranges.
- License: MIT. The official `commaai` dataset card at the pinned revision
  (SHA-256 `3835b02a571a0774917f3204941b83d090c41b727347fd37d63e4ae74d6a9bb4`)
  declares `license: mit` in its YAML front matter, on the same repository
  that hosts the archives. Cite Schafer, Santana, Haden and Biasini, *A
  Commute in Data: The comma2k19 Dataset*, arXiv:1812.05752 (2018).
- Safety: comma.ai deliberately published these trajectories of two company
  recording devices and trimmed them to a public section of I-280. There are
  no names, plates or trip endpoints. Devices appear only as pseudonymous
  16-hex dongle ids, and only in index metadata and file names. No video,
  imagery, CAN or IMU data is emitted.

## Shape and conversion

The natural record is one segment's `global_pose/frame_positions` NPY v1.0
array, with header `{'descr': '<f8', 'fortran_order': False, 'shape': (N, 3)}`.
For each member the recipe:

1. inflates the raw deflate stream;
2. checks CRC32 and size against the central directory;
3. parses the NPY header (body must be N×24 bytes);
4. writes the array body unchanged as little-endian row-major x,y,z float64.

There is no rescaling, reordering or widening. Index min/max come from the
stored float64.

The other members of each segment are excluded on purpose: frame times, GPS
times, orientations, velocities, CAN, IMU, GNSS, raw logs and video. They are
other quantities, or same-source column slices.

Upstream checks enforced by build and verify:

- all values finite;
- geocentric radius in (6.3e6, 6.4e6) m;
- no all-zero rows and no constant component;
- no duplicate payloads.

Inter-frame steps above 4 m are flagged in the index and stats, never
dropped. One segment is flagged: `99c94dc769b5d96e|2018-07-02--19-08-27/10`,
with a single 4.60 m step.

## Accepted output

- Segments: 2,035 (the entire archive population), on 178 routes from 2
  devices (1,653 + 382 segments) over 89 drive dates, 2018-05-01 to
  2018-11-19
- Primary samples: 2,035
- Primary values: 7,291,422
- Primary bytes: 58,331,376
- Minimum sample: 582 values (194 frames). Two segments are below 1,000
  values; both are kept as natural records.
- Median sample: 3,600 values (1,200 frames)
- Maximum sample: 3,606 values (1,202 frames)
- Global value range: −4,274,011.95 to 3,882,266.05 m
- Download on disk: 58,643,956 bytes
- Aggregate decoded SHA-256:
  `62e64e8b3194568ef3b14061301a9cd64801958e775184e1ee1b8cb2df35109f`

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py` passes with no warnings.
- **Verify:** I re-ran `verify.sh` myself and got `verify_ok` with the
  identical aggregate SHA-256. build.sh and verify.sh make no network calls.
- **Independent decode:** my own decoder on 6 members, including the
  194-frame minimum, matched the emitted samples byte for byte, with valid
  CRC and no trailing deflate bytes.
- **Bytes:**
  - 0 values round-trip through float32, and the median mantissa
    trailing-zero count is 1, so float64 is native and fully used.
  - Converted to WGS84, positions fall at 37.571–37.735°N, −122.483 to
    −122.397°E (Peninsula I-280). Ellipsoidal heights are −13 to 167 m.
  - No sample has duplicate rows or zero-length steps.
  - Consecutive segment boundaries never repeat a row (median gap 2.29 m).
  - The median step is about 1.4 m per frame (highway speed).
  - 177 near-stationary segments still carry full-precision jitter. They
    cluster at the SF end of the trimmed section for both devices on many
    dates.
- **Rights:** the pinned card, byte-identical to main, has `license: mit`.
  The HF API shows author `commaai`, not gated and not private. The GitHub
  LICENSE was unreachable (proxy 403). No credential patterns appear in the
  scripts.
- **Novelty:** `novelty.py` for comma2k19, commaai, ecef, laika and
  frame_positions, plus broader trajectory and GPS terms, finds no registry or
  downstream match and no other vehicle-trajectory recipe.
