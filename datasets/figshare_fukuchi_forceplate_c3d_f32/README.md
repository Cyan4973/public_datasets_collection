# Fukuchi Walking Force-Platform Float32

This recipe extracts the native little-endian float32 analog fields from every
unique dynamic walking trial in the CC BY 4.0 Fukuchi et al. C3D archive.

Run:

```bash
bash datasets/figshare_fukuchi_forceplate_c3d_f32/download.sh
bash datasets/figshare_fukuchi_forceplate_c3d_f32/inspect.sh
bash datasets/figshare_fukuchi_forceplate_c3d_f32/build.sh
bash datasets/figshare_fukuchi_forceplate_c3d_f32/verify.sh
```

Each sample is one complete source-order tensor with axes `point frame ×
analog subsample × channel`. Static calibration files, point-coordinate data,
three exact duplicate analog payloads, C3D framing, participant spreadsheets,
and the duplicate gait-event archive are excluded.

The stored float32 values are the C3D analog fields. The channel labels and
metadata identify force-platform measurements, but calibrated physical values
may require the source C3D scale, offset, and platform parameters; the recipe
does not manufacture a rescaled representation.
