# NOAA MarineCadastre AIS 2024-01-01 Float32

Candidate recipe for maritime vessel movement telemetry from NOAA
MarineCadastre AIS data.

The target source is one daily AIS CSV ZIP for 2024-01-01. Natural samples are
one numeric AIS field over preserved source row order. Identifier-like fields
such as MMSI and textual vessel metadata are not emitted.

Run:

```bash
bash staging/noaa_marinecadastre_ais_2024_01_01_f32/download.sh
```

Then build and verify locally:

```bash
bash staging/noaa_marinecadastre_ais_2024_01_01_f32/build.sh
bash staging/noaa_marinecadastre_ais_2024_01_01_f32/verify.sh
```
