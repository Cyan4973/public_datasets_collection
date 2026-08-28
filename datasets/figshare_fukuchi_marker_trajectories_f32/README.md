# Fukuchi walking marker-coordinate trajectories float32

This candidate extracts the native float32 anatomical-marker coordinates from
the same CC BY 4.0 C3D archive used by the accepted Fukuchi force-platform
recipe. Those bytes are not already in the corpus: the existing recipe
explicitly excludes point coordinates and retains only analog force/moment
channels.

Each dynamic walking trial stores 20-22 labeled anatomical markers over 226 to
4,500 frames. The C3D point record interleaves X, Y, Z, and a status/residual
word. This recipe deinterleaves X, Y, and Z into three independent homogeneous
series. One natural sample is one complete trial and one coordinate axis, with
shape:

```text
point_frame x anatomical_marker
```

The fourth point word is not training material. In this archive it contains
only `0.0` and `65535.0` and serves as missing-point status: every nonzero
status position aligns with an exact zero in all three coordinates. Coordinate
zeros are retained without imputation so the emitted matrices preserve the
source representation.

## Why it is new

The accepted 32-bit force-platform family has rank-3
`point_frame x analog_subsample x force/moment channel` tensors. This family
instead contains rank-2 time-by-anatomical-marker kinematic fields. It exposes
smooth articulated motion, synchronized correlations among body landmarks,
periodic gait structure, variable trial duration, and sparse missing-marker
runs. X, Y, and Z are never interleaved.

The accepted result is expected to contain:

- 1,966 unique dynamic walking trials from 42 subject codes;
- 1,966 samples in each of the X, Y, and Z series;
- 5,898 samples and 144,088,704 float32 values overall;
- 576,354,816 primary bytes;
- 4,972 to 99,000 values per sample, with median 9,768; and
- native little-endian float32 coordinates in millimetres.

Fifty static calibration files and three later exact duplicate point payloads
are excluded. Participant spreadsheets, anthropometrics, analog channels,
event annotations, and descriptive metadata are not emitted.

## Run

The downloader first looks for the exact archive already acquired by
`figshare_fukuchi_forceplate_c3d_f32`. If present and its size and MD5 match,
it creates a local hard link (or copy) and performs no network request. If the
verified cache is absent, the user must run the downloader to retrieve the
same pinned Figshare resource.

```sh
bash datasets/figshare_fukuchi_marker_trajectories_f32/download.sh
bash datasets/figshare_fukuchi_marker_trajectories_f32/build.sh
bash datasets/figshare_fukuchi_marker_trajectories_f32/verify.sh
```

Only Python 3 is required. The C3D and ZIP parsing is self-contained.

The source is CC BY 4.0. Walking kinematics can have biometric character even
though subjects are de-identified; do not use the material for participant
identification, linkage, health inference, or biometric profiling.
