# MRO SHARAD EDR Raw Science Telemetry: On-Board-Presummed 8-bit Radar-Sounder Echo Samples (mode SS19, 3600 samples/echo) Int8

- Candidate id: `nasa_pds_sharad_edr_raw_echo_i8`
- Width: int8
- Quantity: Raw received SHARAD echo time samples (real, 26.67 MHz offset-video sampling) after on-board presumming of 4 echoes and 32-to-8-bit requantisation (mode SS19). These are signed 8-bit integers from the raw telemetry, before ground range compression or any processing.
- Source: https://pds-geosciences.wustl.edu/missions/mro/sharad.htm
- Resources: https://pds-geosciences.wustl.edu/mro/mro-m-sharad-3-edr-v1/mrosh_0004/index/index.tab, https://pds-geosciences.wustl.edu/mro/mro-m-sharad-3-edr-v1/mrosh_0004/label/science8bit.fmt, https://pds-geosciences.wustl.edu/mro/mro-m-sharad-3-edr-v1/mrosh_0004/data/edr31xxx/edr3103501/e_3103501_001_ss19_700_a.lbl, https://pds-geosciences.wustl.edu/mro/mro-m-sharad-3-edr-v1/mrosh_0004/data/edr31xxx/edr3103501/e_3103501_001_ss19_700_a_s.dat
- License: NASA SMD open scientific data policy (NASA PDS public data; MRO-M-SHARAD-3-EDR-V1.0)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: It is Science Mission Directorate (SMD) policy, consistent with NASA and Federal policies, that information produced from SMD-funded scientific research activities be made publicly available.
- Natural record: One EDR observation product (the *_s.dat science telemetry table): a continuous along-track sequence of echoes, each row 3786 bytes = 186-byte ancillary header + 3600 int8 ECHO_SAMPLES. Sample = the rows x 3600 int8 echo matrix of one product. The echo row (3600 values) is the alternative natural sub-record.
- Estimated samples: 10
- Estimated primary values: 430,000,000
- Estimated download bytes: 455,000,000
- Estimated primary bytes: 430,000,000
- Decode path: curl selected *_s.dat products (with their .lbl) after choosing them from index/index.tab: INSTRUMENT_MODE_ID = SS19 and short durations of about 60-90 s, i.e. about 10-16k rows. Check in the label: RECORD_BYTES=3786, INSTRUMENT_MODE_ID=SS19, '08-bit precision' in the mode description. Then slice row[186:3786] per row and store as int8 (bytes kept verbatim). Pure stdlib.
- Novelty kind: new_quantity
- Measurement type: radar_sounder_raw_echo
- Instrument line: mro_sharad
- Archive collection: pds-geosciences.wustl.edu/mro
- Novelty evidence: novelty.py --url .../mro-m-sharad-3-edr-v1/: same host only (7 recipes). The only SHARAD recipe is nasa_pds_sharad_radargram_f32, a different product: US RDR, ground-processed and range-compressed float32 radargrams from a different data set and different files. No raw radar-sounder telemetry exists at any width. The closest 8-bit int families are EM302 water-column amplitudes (dB-like magnitudes) and Myo EMG i8. These EDR samples are raw chirp echoes: zero-mean, near-Gaussian, about 86-93 distinct levels per row.
- Homogeneity: Restrict to one on-board processing mode: SS19 (presum 4, 8-bit, PRI 1428 us). SS19 is 9,970 of 26,592 products in volume MROSH_0004. Exclude the 4- and 6-bit modes (science4bit/science6bit formats) and other presum settings. Keep the manual gain setting as auxiliary metadata if desired. Choose products from different orbits and latitudes within one volume or a few, with DATA_QUALITY_ID=0.
- Risks: (1) The same instrument line (mro_sharad) already exists at 32 bits as processed radargrams. Argue new_quantity (raw telemetry vs processed product, different files); a judge may still weigh it as the same instrument. (2) Products are large (one 392 s product is 260 MB), so pick short products to keep about 8-12 samples under about 500 MB. (3) Noise-like int8 might sit near uci_emg_gestures_i8 or ASCAD traces on the byte gate. (4) SHARAD is an ASI-provided instrument; rights rest on the NASA PDS public archive, the same basis as the accepted SHARAD RDR recipe.
- Probe evidence: index.tab for MROSH_0004 is live (26,592 products; mode counts SS4 14,795, SS19 9,970, SS11 1,434). For SS19, 1,512 products have durations of 60-150 s (median 315 s). The label of E_3103501_001_SS19_700_A gives RECORD_BYTES 3786, 68,616 rows and a mode description of 'summing 04 sequential echoes, and converting the result from 32-bit precision to 08-bit precision'. science8bit.fmt lists ECHO_SAMPLES as 3600 x 8-bit MSB_INTEGER. HEAD on the _s.dat gave content-length 259,780,176 (= 68,616 x 3786). A 206 range GET of 3 rows (11,358 bytes) at row 30000 decoded row[186:] to values in -52..54 with 86-93 distinct levels, roughly zero-mean.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_230754.jsonl`).
