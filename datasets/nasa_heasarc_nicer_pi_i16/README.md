# NASA HEASARC NICER X-ray photon PI int16

This recipe decodes the native signed-16-bit `EVENTS.PI` pulse-invariant
energy-channel column from 31 complete cleaned NICER/XTI observations in
NASA's public HEASARC archive. One complete observation is one variable-length
photon-event sample.

Run:

1. `bash datasets/nasa_heasarc_nicer_pi_i16/download.sh`
2. `bash datasets/nasa_heasarc_nicer_pi_i16/build.sh`
3. `bash datasets/nasa_heasarc_nicer_pi_i16/verify.sh`

The dependency-free decoder strictly parses FITS headers and binary-table row
layouts. It accepts only scalar `TFORM=1I` PI columns with identity scaling,
unit `chan`, and the declared `-32768` null sentinel. Selected values are
preserved in event-row order and converted only from FITS big-endian storage to
canonical little-endian int16.
