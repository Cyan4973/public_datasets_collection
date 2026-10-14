# ECMWF IFS HRES Open Data (0p4-beta, 2023): 500 hPa Relative Vorticity 24 h Forecast Fields, Native GRIB2 Simple-Packed 16-bit Codes UInt16

- Candidate id: `ecmwf_opendata_ifs_vo500_grib_u16`
- Width: uint16
- Quantity: GRIB2 template-5.0 simple-packed 16-bit integer codes X of 500 hPa relative vorticity (s-1; GRIB2 discipline 0, cat 2, param 12) from the IFS 00z 24 h forecast on the 0.4° global grid (900x451). Physical value = R + X*2^E with per-message R and E kept as metadata.
- Source: https://registry.opendata.aws/ecmwf-forecasts/
- Resources: https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com/20230301/00z/0p4-beta/oper/20230301000000-24h-oper-fc.grib2, https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com/20230301/00z/0p4-beta/oper/20230301000000-24h-oper-fc.index, https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com/?list-type=2&delimiter=/&prefix=20230301/00z/
- License: CC-BY-4.0 (plus ECMWF Terms of Use)
- License evidence: https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/ecmwf-forecasts.yaml
- License quote: This ECMWF data is published under a Creative Commons Attribution 4.0 International license (CC-BY-4.0) and the ECMWF Terms of Use
- Natural record: One GRIB2 message = one complete global field (vo at 500 hPa, step 24 h) of one 00z run: 405,900 values. One sample per day, 2023-02-01 to 2024-01-31.
- Estimated samples: 365
- Estimated primary values: 148,153,500
- Estimated download bytes: 303,000,000
- Estimated primary bytes: 296,307,000
- Decode path: For each day, curl the small JSON-lines .index (about 18 KB) and pick the line with param=vo, levelist=500 to get _offset and _length (811,996). Range-GET exactly that message (curl -r) into its own file. The Python parser walks GRIB2 sections 0-8 and asserts section 3 template 0 with 405,900 points, section 5 template 0 with 16 bits, and section 6 bitmap indicator 255. Section 7 is 405,900 big-endian uint16; byteswap to little-endian. R/E/D go into the index as auxiliary metadata.
- Novelty kind: new_source
- Measurement type: sim_atmos_field
- Instrument line: ECMWF IFS HRES deterministic forecast, open-data 0p4-beta GRIB2 simple packing
- Archive collection: ecmwf_open_data
- Novelty evidence: novelty.py --url ecmwf-forecasts bucket: no URL matches. --terms ECMWF/vorticity/GRIB: only generic 'open data' hits on unrelated recipes. sim_atmos_field has 4 members, all 32/64-bit float (WeatherBench2 ERA5 f32, ClimSim f64, GEOS-Chem f64, CESM2 f32), and none at 16-bit. No GRIB-derived recipe exists anywhere in datasets/ or the registry. Archive ecmwf_open_data: 0 members.
- Homogeneity: One parameter, one pressure level, one grid (0p4-beta 900x451 regular lat-lon), one run time (00z), one lead time (24 h), one packing (5.0, 16 bits, no bitmap) for every sample. The 2023-06-27 IFS cycle 48r1 upgrade falls inside the window; the builder may narrow to 2023-07-01 to 2024-01-31 (215 samples) if strict model-version homogeneity is wanted. Only 16-bit-packed parameters qualify; 2t, msl and similar are 12-bit packed and are excluded.
- Risks: (1) The S3 bucket returns 'SlowDown' (503) under bursty requests; download.sh needs retries with backoff and modest pacing. (2) The judge may question whether GRIB packed codes count as native; they are the stable machine-facing stored representation, like a scaled-int NetCDF variable. (3) The 0p4-beta stream ends in Feb 2024 (later 0p25 uses CCSDS template 5.42, 12-bit), so do not extend past 2024-01. (4) Sibling params (d500, vo850, tp) share the same files and must not be proposed as separate families.
- Probe evidence: Listed 20230301/00z/0p4-beta/oper (24h file 50.5 MB plus .index 17.9 KB). Index line for vo/500: _length 811,996 (=405,900*2+196). Range-fetched its first 200 bytes: 'GRIB' ed.2, total length 811,996, section 3 npts 405,900 template 0, section 4 cat 2 param 12, section 5 template 0, R=-0.0011186, E=-32743 (sign-magnitude), D=0, bits=16, section 6 bitmap 255. The bucket starts 20230118; 0p4-beta is present through 20240201, and 20240301 has only ifs/aifs. Lengths in the 2023 index show tp, vo and d are 16-bit while 2t, msl, gh, t, u, v are 12-bit. The 2025 0p25 stream uses template 42 (CCSDS) at 12 bits, so it is excluded.

Proposed by the autocollect scout on 2026-10-14 (transcript `.data/pipeline/logs/scout_16bit/scout.20261014_132438.jsonl`).
