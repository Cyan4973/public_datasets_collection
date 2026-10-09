# Cassini ISS Narrow-Angle Camera Raw EDR Frames with On-Board 12-to-8-bit TABLE Conversion (1024x1024, Saturn system 2008) UInt8

- Candidate id: `nasa_pds_cassini_iss_nac_lut8_raw_u8`
- Width: uint8
- Quantity: Raw Cassini ISS NAC detector DN after the on-board 12-to-8-bit look-up-table (DATA_CONVERSION_TYPE='TABLE'), one full-resolution 1024x1024 frame per EDR, with the 24-byte binary line-prefix and the VICAR label stripped.
- Source: https://planetarydata.jpl.nasa.gov/img/data/cassini/cassini_orbiter/
- Resources: https://planetarydata.jpl.nasa.gov/img/data/cassini/cassini_orbiter/coiss_2050/index/index.tab, https://planetarydata.jpl.nasa.gov/img/data/cassini/cassini_orbiter/coiss_2050/index/index.lbl, https://planetarydata.jpl.nasa.gov/img/data/cassini/cassini_orbiter/coiss_2050/data/1604723153_1604729503/N1604723153_1.IMG
- License: NASA SMD open scientific data (NASA PDS mission data, US Government work, no copyright)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: information produced from SMD-funded scientific research activities be made publicly available ... Mission data are released as soon as possible
- Natural record: One ISS EDR image file (VICAR, FORMAT='BYTE', NL=NS=1024, NBB=24 binary prefix bytes per line, NLB=1 binary header record): 1,048,576 uint8 pixels.
- Estimated samples: 300
- Estimated primary values: 314,572,800
- Estimated download bytes: 325,000,000
- Estimated primary bytes: 314,572,800
- Decode path: Select rows from the volume index.tab (stdlib csv) with DATA_CONVERSION_TYPE='TABLE', INSTRUMENT_ID='ISSNA', INSTRUMENT_MODE_ID='FULL', INST_CMPRS_TYPE='LOSSLESS' and MISSING_LINES=0. curl each IMG and parse the VICAR label (LBLSIZE, RECSIZE=1048, NL, NS, NBB=24, NLB=1, FORMAT='BYTE'). Skip LBLSIZE plus NLB*RECSIZE, then for each of the 1024 records drop the 24 prefix bytes and keep 1024 bytes. Probe-verified: 4 frames each produced exactly 1,048,576 bytes.
- Novelty kind: new_source
- Measurement type: raw_space_frame
- Instrument line: Cassini ISS Narrow-Angle Camera CCD (12-bit ADC, on-board 8-bit LUT conversion)
- Archive collection: PDS Imaging Node planetarydata.jpl.nasa.gov/img/data/cassini/cassini_orbiter (COISS_2xxx)
- Novelty evidence: novelty.py --url .../coiss_2050/ --terms 'cassini iss' coiss ISSNA: no matches in recipes, registry, ledger or downstream. Cassini RADAR BIDR and RPWS WBR (8-bit) and VIMS (16-bit) are other instruments. Read-only zlsim feature probe on 4 random TABLE NAC frames: nearest library distances 0.040-0.073 (video_chroma_cb / mitbih / hc18 ultrasound); distance to Voyager ISS raw is 0.118-0.188 and to the JunoCam candidate 0.071-0.127. Frames 1 and 4 (rings, 0.040-0.049 to video chroma) are borderline on features, frames 2-3 clearly novel.
- Homogeneity: One camera (ISS NAC), one readout mode (FULL 1024x1024), one on-board conversion (12-to-8 TABLE LUT; 12BIT 16-bit products and SUM2/SUM4 excluded), lossless compression only, and contiguous 2008 extended-mission volumes (coiss_2050..2052, about 2,500 eligible frames per volume). Take about 300 frames spread evenly through the index, all targets in the Saturn system.
- Risks: Feature distance to video_chroma_cb_u8 is about 0.04-0.05 for ring frames, so if the median lands under 0.05 the compression test decides. Mixing ring and moon frames gives in-family variety but is still one sensor regime. Dark-sky frames could be dominated by a few low DN, so the builder should check mode share or skip frames whose EXPECTED_MAXIMUM is very low. The line prefix holds binary telemetry and must be removed, not emitted.
- Probe evidence: coiss_2050 index.tab: 4,461 rows; TABLE+NAC = 1,923 (+175), TABLE+WAC = 612 (+175), 12BIT = 1,576. Range GET of the first 20 KB of N1604723153_1.IMG shows the VICAR label LBLSIZE=3144 FORMAT='BYTE' RECSIZE=1048 NL=1024 NS=1024 NBB=24 NLB=1 DATA_CONVERSION_TYPE='TABLE' INST_CMPRS_TYPE='LOSSLESS'. Volumes coiss_2001..2116 are listed. Four full frames (about 1.07 MB each) decoded to 1,048,576 bytes each.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_085042.jsonl`).
