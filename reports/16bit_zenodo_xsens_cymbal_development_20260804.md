# Xsens cymbal-performance landmarks int16 development — 2026-08-04

## Outcome

Accepted `zenodo_xsens_cymbal_landmarks_i16`, 71 native signed-int16 Xsens
inertial-motion-capture recordings from Zenodo record `21710617`, *Cymbal
percussion: multimodal motion capture, audio and video (2011)*, DOI
`10.5281/zenodo.21710617`, released under CC BY 4.0.

## Why this adds a new numeric shape

The accepted TUM RGB-D motion-capture family contains a single rigid camera's
float64 translation and quaternion path. This family contains 64 simultaneous
full-body anatomical-landmark XYZ trajectories during percussion gestures,
sampled at 120 Hz. It adds multibody articulated motion, inter-landmark
geometry, and repeated performance dynamics in native int16 storage.

## Source interpretation

All 71 C3D files declare positive `POINT:SCALE`, Intel byte order, 64 points,
millimetre units, 120 Hz point rate, and Xsens MVN Studio 3.0 export. Positive
C3D point scale means native four-word signed-int16 point records. The recipe
retains the three XYZ coordinate words; the fourth packed residual/camera word
is validated as zero for all 4,854,720 point records and excluded.

The 64 exact labels span hips, spine, head, shoulders, arms, hands, legs, and
feet. Physical millimetres are obtained by multiplying raw words by the
per-recording positive scale, which is retained in the index. No numeric
conversion or rescaling is performed.

## Accepted material

- 71 complete performance takes
- 75,855 frames, from 81 through 2,721 frames per take (median 965)
- fixed 64 landmarks and XYZ coordinates
- 14,564,160 signed-int16 values and 29,128,320 numeric bytes
- 71 unique payload hashes
- global raw range -32767 through 32767
- at least 4,852 distinct values per take
- 60,835 zero coordinate words overall and no missing points
- zlib-9 ratios approximately 0.265 through 0.889, median about 0.530

The recipe excludes ZIP/C3D framing, parameter text, the naming key, audio,
video, optical-camera captures, and all other modalities.

## License and safety

Zenodo explicitly declares CC BY 4.0. The recording contains an unnamed adult
performer's full-body movement, which may have biometric character; the
manifest marks it as personal data and prohibits identification, linkage, or
biometric profiling. No performer name, demographic field, audio, or video is
included in the emitted samples.
