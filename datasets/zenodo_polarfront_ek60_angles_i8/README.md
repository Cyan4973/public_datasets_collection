# PolarFront EK60 Split-Beam Angles Int8

This recipe extracts the two native signed-byte split-beam angle components
from the same exact CC0 Simrad EK60 recording used by the accepted PolarFront
power recipe.

Run:

```bash
bash datasets/zenodo_polarfront_ek60_angles_i8/download.sh
bash datasets/zenodo_polarfront_ek60_angles_i8/inspect.sh
bash datasets/zenodo_polarfront_ek60_angles_i8/build.sh
bash datasets/zenodo_polarfront_ek60_angles_i8/verify.sh
```

`download.sh` first reuses the validated accepted-recipe cache, using a hard
link where possible. It only contacts Zenodo if that exact local source is not
available.

The source contains 1,147 synchronized pings at 18, 38, and 120 kHz. Every
channel contributes one complete 3,188-bin alongship profile and one complete
3,188-bin athwartship profile. The recipe deinterleaves those documented RAW0
mode-3 signed bytes without numerical conversion. Acoustic power, framing,
configuration structures, and NMEA navigation text are excluded.
