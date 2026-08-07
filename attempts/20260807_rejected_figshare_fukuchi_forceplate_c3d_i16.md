# Rejected: Fukuchi walking force-platform C3D at 16 bits

## Candidate

- Dataset ID: `figshare_fukuchi_forceplate_c3d_i16`
- Figshare article: `5722711`, version 5
- DOI: `10.6084/m9.figshare.5722711.v5`
- Title: *A public data set of overground and treadmill walking kinematics and
  kinetics of healthy individuals*
- License: CC BY 4.0

The proposed primary material was the synchronized force-platform analog
channel matrix in each walking C3D recording. This would have added
ground-reaction force and moment waveforms rather than another body-landmark
coordinate tensor.

## Bounded preflight

The Figshare file inventory and remote ZIP central directories established:

- `WBDSc3d.zip`: 732,874,413 bytes, 2,019 C3D members;
- `WBDSc3dWithGaitEvents.zip`: 732,934,431 bytes, 2,011 C3D members; and
- 4,030 C3D members totaling approximately 2.24 GB uncompressed.

The preflight fetched no complete archive or C3D file. It range-read ZIP
directories and bounded member prefixes for 40 members selected across sorted
file sizes and names. The selection included static calibration and overground
walking trials from multiple participants.

All 40 C3D file headers use Intel parameter storage and declare negative
`POINT:SCALE`. The observed scale range was approximately `-0.11774338` through
`-0.04323037`; zero members had a positive scale. In the C3D data model, a
negative point scale selects floating-point data records, so both point and
analog samples occupy native float32 fields rather than signed or unsigned
16-bit words.

## Decision

Reject this exact source for the 16-bit collection. Quantizing the force data
to int16 would manufacture a representation absent from the source and would
violate the native-width objective.

The domain and license remain attractive. A separate float32 recipe may retain
complete force-platform channel matrices after validating `ANALOG` and
`FORCE_PLATFORM` parameters, channel labels, physical units, participant
privacy context, full-record distributions, and natural trial boundaries.
