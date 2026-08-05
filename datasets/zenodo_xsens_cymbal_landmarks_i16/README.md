# Xsens Cymbal-Performance Landmarks Int16

This recipe decodes 71 full-body Xsens MVN inertial-motion-capture recordings
from Zenodo record `21710617`, released under CC BY 4.0. A percussionist
performed structured cymbal strokes while a 64-landmark body model was sampled
at 120 Hz.

Run:

```bash
bash datasets/zenodo_xsens_cymbal_landmarks_i16/download.sh
bash datasets/zenodo_xsens_cymbal_landmarks_i16/inspect.sh
bash datasets/zenodo_xsens_cymbal_landmarks_i16/build.sh
bash datasets/zenodo_xsens_cymbal_landmarks_i16/verify.sh
```

Every C3D uses positive-scale Intel integer storage. The recipe emits one
complete `[frame, anatomical_landmark, xyz]` little-endian signed-int16 tensor
per take. Physical millimetres equal each raw coordinate multiplied by that
take's C3D point scale, retained in the sample index. The packed fourth C3D
point word is excluded after validation that it is zero for every point.

These public body-motion trajectories may be biometric. The recipe excludes
audio, video, names, demographics, and free text; users must not attempt to
identify the unnamed performer.
