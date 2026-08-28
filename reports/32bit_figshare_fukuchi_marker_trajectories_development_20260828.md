# Fukuchi Walking Marker Trajectories Float32 — 2026-08-28

## Outcome

`figshare_fukuchi_marker_trajectories_f32` adds 5,898 native little-endian
float32 samples containing 144,088,704 values and 576,354,816 bytes. The X, Y,
and Z coordinate families each contain 1,966 complete dynamic walking trials
and 48,029,568 values.

Each sample is a variable-size rank-2 matrix with axes
`point_frame x anatomical_marker`. Trials contain 20-22 labeled markers over
226-4,500 frames, sampled at 100 or 150 Hz. Sample sizes range from 4,972 to
99,000 values, with median 9,768.

## Why this is new

The existing `figshare_fukuchi_forceplate_c3d_f32` recipe intentionally emits
only the archive's analog force/moment blocks and explicitly excludes point
coordinates. Its samples have shape
`point_frame x analog_subsample x force/moment channel`.

This family uses different source fields and a different numerical structure:
smooth time-by-landmark coordinate matrices describing articulated human
motion. It exposes synchronized correlations across anatomical markers,
periodic gait evolution, variable trial duration, and sparse missing-marker
runs. X, Y, and Z remain separate homogeneous series rather than being
interleaved into coordinate triples.

## Source reuse and license

The exact 732,874,413-byte `WBDSc3d.zip` archive is shared with the accepted
force-platform family and pinned by Figshare MD5
`5d93531eab7acc8ebe786145cd26eea8`. The new downloader can hard-link the
already verified local archive, avoiding another network transfer, while
remaining able to acquire and validate the original Figshare resource on a
fresh installation.

Figshare article `5722711` version 5, DOI
`10.6084/m9.figshare.5722711.v5`, explicitly declares CC BY 4.0. Attribution
to Claudiane Fukuchi, Reginaldo Fukuchi, and Marcos Duarte must be preserved.

The recordings are de-identified but human walking kinematics can have
biometric character. Participant spreadsheets and anthropometrics are
excluded, and the recipe prohibits identification, linkage, health inference,
and biometric profiling.

## Representation

All dynamic files use Intel little-endian C3D storage and negative
`POINT:SCALE`, which specifies native float32 point records. Each point tuple
contains X, Y, Z, and a fourth status/residual word. The recipe copies the
three coordinate words exactly into independent row-major matrices; it does
not scale, interpolate, transform coordinates, or mix axes.

The fourth word is excluded from training. Across the retained trials it is
either `0.0` or `65535.0`. All 124,944 nonzero-status positions align exactly
with zero X, Y, and Z coordinates. Those 374,832 coordinate zeros are retained
as the source's missing-marker representation rather than imputed.

## Verification

Build and verification passed on 2026-08-28. The independent verifier reparsed
all 2,019 ZIP members and recomputed every coordinate sample from the source.
It confirmed:

- 50 static calibration members excluded;
- three later exact duplicate point payloads excluded;
- 1,966 unique dynamic trials from 42 subject codes;
- 1,638 overground and 328 treadmill trials;
- five exact marker-label/rate schemas;
- finite, nonconstant coordinate samples with no duplicate outputs;
- exact little-endian source-word preservation; and
- agreement among source-derived hashes, the sample index, stored statistics,
  and all 576,354,816 output bytes.
