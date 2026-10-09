# CDIP (Scripps) Datawell DWR-M3 Directional Waverider Raw Vertical Heave Displacement Time Series at 1.28 Hz, Native Float32

- Candidate id: `cdip_waverider_m3_z_displacement_f32`
- Width: float32
- Quantity: Buoy vertical (heave) displacement in metres (xyzZDisplacement) sampled at 1.28 Hz. The Datawell Mk III telemetry gives 1 cm resolution, stored as float32 in the CDIP archive NetCDF.
- Source: https://thredds.cdip.ucsd.edu/thredds/catalog/cdip/archive/catalog.html
- Resources: https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/archive/100p1/100p1_d10.nc.dds, https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/archive/100p1/100p1_d10.nc.dods?xyzZDisplacement[0:1:N]
- License: CDIP: redistribution and use without restriction
- License evidence: https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/archive/100p1/100p1_d10.nc.das
- License quote: license "These data may be redistributed and used without restriction."
- Natural record: One buoy deployment's continuous heave-displacement record. Take one bounded contiguous window (e.g. 14 days = about 1.55M values) per deployment, one window per deployment, no sharding.
- Estimated samples: 40
- Estimated primary values: 62,000,000
- Estimated download bytes: 250,000,000
- Estimated primary bytes: 248,000,000
- Decode path: Server-side OPeNDAP projection with curl: <deployment>.nc.dods?xyzZDisplacement[a:1:b]. Parse the DDS text and XDR body ('Data:\n', then two big-endian int32 lengths, then big-endian float32 values) and write little-endian float32. Select deployments whose NC_GLOBAL title says 'Datawell DWR-M3' via the .das. Downloaded bytes are almost exactly the kept bytes. Verified locally on a 2,304-value subset.
- Novelty kind: new_modality
- Measurement type: wave_buoy_displacement
- Instrument line: datawell_dwr_mk3_waverider
- Archive collection: thredds.cdip.ucsd.edu
- Novelty evidence: novelty.py --url thredds.cdip.ucsd.edu --terms cdip waverider datawell: no source match ('displacement' hits are unrelated). The only wave family is noaa_ndbc_wave_spectral_density_f64 (derived spectra, 64-bit). --type wave_buoy_displacement: 0 families.
- Homogeneity: One buoy model (DWR-M3, 1.28 Hz, 1 cm telemetry resolution), one variable (Z heave), one unit, one archive processing. Spread across many stations and deployments (100p1 has at least 10 deployments; dozens of stations). Exclude DWR-G4/MkIV/Spotter deployments, which differ in resolution and rate.
- Risks: Values sit on a 0.01 m lattice (106 distinct values in 2,304 samples), so the stream is compressible and could approach other quantized float32 families (e.g. Open-Meteo) on the byte gate. Its fast zero-mean oscillation (about 8-sample periods) should still differ. Gaps and flagged samples (xyzFlagPrimary) need a missing-value policy. The THREDDS OPeNDAP server may throttle large requests, so chunk requests.
- Probe evidence: The THREDDS catalog for 100p1 lists d01-d10 files of 0.37-1.2 GB. The .dds shows Float32 xyzZDisplacement[xyzCount = 50743295] plus X/Y and flags. The .das NC_GLOBAL has the license string above, with title 'Datawell DWR-M3 directional buoy located near TORREY PINES OUTER'. A .dods request for xyzZDisplacement[1000000:1:1002303] returned 2,304 floats in -0.70..0.64 m, multiples of 0.01.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_225934.jsonl`).
