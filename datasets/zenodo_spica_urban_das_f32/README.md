# Spica Urban DAS MiniSEED Float32

This staged candidate collects the one-day distributed-acoustic-sensing (DAS)
waveforms deposited with Spica et al.'s *Urban Seismic Site Characterization by
Fiber-Optic Seismology*. The exact Zenodo record is licensed CC BY 4.0.

The archive contains nine MiniSEED v2 streams at ordered virtual-station
positions along the sensing fiber. Each stream is sampled at 50 Hz and stored
as native MiniSEED encoding 4 (IEEE float32). One complete deposited
channel/day stream becomes one natural sample. The decoder preserves every
float32 bit pattern and converts the word order declared by blockette 1000 to
canonical little-endian output.

This is not a new scientific domain relative to the accepted integer seismic
waveforms. Its value is a new sensing geometry and representation: synchronized
day-long float32 traces from multiple positions on a distributed fiber, rather
than short conventional-seismometer windows in integer counts.

Run:

```bash
bash datasets/zenodo_spica_urban_das_f32/download.sh
bash datasets/zenodo_spica_urban_das_f32/build.sh
bash datasets/zenodo_spica_urban_das_f32/verify.sh
```

The download is 92,177,152 bytes. The downloader pins its size and MD5 and
performs a semantic MiniSEED preflight. Build and verification use only the
local archive after acquisition.

Validated output: 9 synchronized channel/day samples, each containing
4,320,000 values over the same gap-free 24-hour interval at 50 Hz. Aggregate
output is 38,880,000 float32 values and 155,520,000 bytes.
