# PolarFront EK60 Backscatter Power Int16

This recipe decodes native signed-int16 acoustic power vectors from one exact
keel-mounted Simrad EK60 split-beam echosounder recording acquired during the
PolarFront 2022-05 cruise and released under CC0.

Run:

```bash
bash datasets/zenodo_polarfront_ek60_power_i16/download.sh
bash datasets/zenodo_polarfront_ek60_power_i16/inspect.sh
bash datasets/zenodo_polarfront_ek60_power_i16/build.sh
bash datasets/zenodo_polarfront_ek60_power_i16/verify.sh
```

The source contains 1,147 synchronized pings at 18, 38, and 120 kHz. Each
channel contributes one complete 3,188-bin `RAW0` power vector. The recipe
emits these 3,441 vectors in source datagram order without numeric conversion.
Simrad framing, angle bytes, calibration structures, and NMEA navigation text
are validated as context but excluded from training samples.
