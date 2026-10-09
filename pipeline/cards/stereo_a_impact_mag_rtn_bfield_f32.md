# STEREO-Ahead IMPACT/MAG Level-1 Interplanetary Magnetic Field Vectors in RTN Coordinates (daily CDF, ~8 Hz), Native Float32

- Candidate id: `stereo_a_impact_mag_rtn_bfield_f32`
- Width: float32
- Quantity: Heliospheric (solar-wind) magnetic field vector Br, Bt, Bn and |B| in nT, measured in situ by the STEREO-A fluxgate magnetometer
- Source: https://stereo-ssc.nascom.nasa.gov/data/ins_data/impact/level1/ahead/mag/RTN/
- Resources: https://stereo-ssc.nascom.nasa.gov/data/ins_data/impact/level1/ahead/mag/RTN/2020/01/STA_L1_MAGB_RTN_20200102_V06.cdf, https://stereo-ssc.nascom.nasa.gov/data/ins_data/impact/level1/ahead/mag/RTN/, https://science.data.nasa.gov/about/license
- License: CC0 1.0 (NASA Science Data license for NASA-led mission data; STEREO is a NASA STP mission; the in-file Rules_of_use attribute is empty, so no restrictive notice)
- License evidence: https://science.data.nasa.gov/about/license
- License quote: Unless the data file is marked with a restrictive notice or license, data that is provided from a NASA-led mission including observations, engineering, calibration, and auxiliary data are licensed as Creative Commons Zero. There are no restrictions on the usage of these data.
- Natural record: One UTC-day Level-1 CDF: BFIELD variable, N records x 4 float32 (about 457,731 records, about 1.83M values on 2020-01-02)
- Estimated samples: 50
- Estimated primary values: 90,000,000
- Estimated download bytes: 550,000,000
- Estimated primary bytes: 360,000,000
- Decode path: CDF v2.6 (magic CDF2 6002), uncompressed (0x0000FFFF, CPR offset -1). Pure-stdlib parser: CDR -> GDR -> zVDR chain (BFIELD: DataType 44 CDF_FLOAT, dims (4,), big-endian 32-bit offsets) -> VXR -> VVR blocks; struct '>f' -> little-endian float32. Drop or flag FILLVAL (-1e31) records per a documented policy.
- Novelty kind: new_quantity
- Measurement type: interplanetary_magnetic_field
- Instrument line: stereo_impact_mag_fluxgate
- Archive collection: stereo-ssc.nascom.nasa.gov/impact/level1
- Novelty evidence: novelty.py --url stereo-ssc... --terms impact_mag/'interplanetary magnetic': no matches. The only spacecraft-magnetometer family is gfz_gracefo_fgm_acal_bnec_f64 (64-bit, LEO, Earth's main field of tens of thousands of nT); usgs_geomag_observatory_minute_f32 is ground-based. A heliospheric IMF series of a few nT with turbulent sign changes is absent at 32-bit and downstream. noaa_swpc_dscovr_solar_wind_f32 is a staging draft (1-min plasma/mag JSON), not this instrument or cadence.
- Homogeneity: STEREO-A only (exclude Behind, which ended 2014), RTN frame only (exclude SC frame), V06 Level-1 only. One unit (nT). About 50 days spread over 2007-2025. Keep the native 4-component records, or emit Br/Bt/Bn and |B| as separate series.
- Risks: Sample rate varies within and between days (normal vs burst telemetry; file sizes 5.5-13 MB), but the quantity and unit are constant. CDF parsing is custom work (v2 layout, VXR chains), with no prior recipe. The mission team (UC Berkeley/UCLA) gives no explicit license, so rights rely on NASA's CC0 policy. The host has no HTTPS directory index in some trees, but HTTPS works here. SPDF/CDAWeb mirrors timed out, so do not rely on them.
- Probe evidence: HTTPS listing 200 OK: years 2006-2026 under ahead/mag/RTN; daily files STA_L1_MAGB_RTN_YYYYMMDD_V06.cdf of 5.5-13 MB. 64 KB range GET parsed: CDF 2.6 uncompressed; zVariables Epoch (EPOCH), BFIELD (CDF_FLOAT, dims 4, maxrec 457730), MAGFLAGUC (UINT4), CART_LABL_1, FILTER_VALUE; global attributes PI_name 'J. Luhmann', Mission_group 'STEREO', Rules_of_use empty.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_164906.jsonl`).
