# GRAIL LGRS Level-1B Dual-One-Way Ka-Band Inter-Satellite Ranging (KBR1C): Biased Range, Range Rate and Range Acceleration, Float64

- Candidate id: `grail_lgrs_kbr1c_ka_band_ranging_f64`
- Width: float64
- Quantity: Inter-spacecraft range between GRAIL-A and GRAIL-B from the Lunar Gravity Ranging System. Biased range is in m (about 2.2e5 m, printed to 1e-10 m, 16 significant digits); range rate is in m/s and range acceleration in m/s², both at full float precision. Cadence is 5 s.
- Source: https://pds-geosciences.wustl.edu/grail/grail-l-lgrs-3-cdr-v1/grail_0101/
- Resources: https://pds-geosciences.wustl.edu/grail/grail-l-lgrs-3-cdr-v1/grail_0101/level_1b/, https://pds-geosciences.wustl.edu/grail/grail-l-lgrs-3-cdr-v1/grail_0101/level_1b/2012_04_10/kbr1c_2012_04_10_x_04.asc, https://pds-geosciences.wustl.edu/grail/grail-l-lgrs-3-cdr-v1/grail_0101_230316.md5, https://pds-geosciences.wustl.edu/grail/grail-l-lgrs-3-cdr-v1/grail_0101/document/
- License: NASA SMD Open Scientific Data Policy (NASA PDS archive; same LicenseRef as the accepted orex_ola_l2_lidar_point_xyz_f64 and fermi_gbm recipes)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: 'NASA holds this information, including publications, data, and software, as a public trust to increase knowledge and serve the public good. It is Science Mission Directorate (SMD) policy, consistent with NASA and Federal policies, that information produced from SMD-funded scientific research activities be made publicly available.'
- Natural record: One daily KBR1C_YYYY_MM_DD_X_04.ASC product: about 17,280 records per day at 5 s. Emit three primary series per day, each from the same records: biased_range (col 2), range_rate (col 3) and range_accl (col 4). gps_time can be an auxiliary series.
- Estimated samples: 591
- Estimated primary values: 10,200,000
- Estimated download bytes: 1,060,000,000
- Estimated primary bytes: 82,000,000
- Decode path: Direct per-file HTTPS GET of the .asc files (about 5.4 MB each, 197 days listed in grail_0101_230316.md5 with checksums). The format is plain whitespace-separated ASCII documented in the PDS3 .lbl and DPSIS.PDF Table 43. Python float() then struct '<d'. Validate against the md5 manifest. Pure stdlib.
- Novelty kind: new_modality
- Measurement type: intersatellite_ranging
- Instrument line: grail_lgrs_ka_band_dowr
- Archive collection: pds-geosciences.wustl.edu/grail
- Novelty evidence: novelty.py --url .../grail-l-lgrs-3-cdr-v1/grail_0101/ --terms KBR 'biased range' GRAIL dual-one-way: same host only (nasa_pds_gravity_harmonics_f64, mola, sharad are baseline recipes, not this effort). The 'grail' term matches only the GRGM1200A Level-2 spherical-harmonic gravity model, a different product and file. Nothing in the vocabulary covers inter-satellite microwave ranging. The nearest, laser_range and gnss_carrier_phase, are different instruments and observables.
- Homogeneity: One instrument (LGRS Ka-band DOWR), one processing level and version (L1B RL04, KBR1C), one cadence, one mission phase set (2012-03-01..2012-12, 197 days). Each series has a single unit. Range, rate and acceleration are kept as separate series ids rather than mixed.
- Risks: Some days may be partial or calibration/maneuver days with flagged records. The builder should keep whole days and record qualflg-based exclusions rather than splicing. The extraction ratio is about 8% (text to f64 for 3 of about 20 columns), but no leaner source exists and the absolute kept signal (~80 MB) is solid. Range is smooth and quasi-periodic, so delta-compressibility is high. Statistics should still differ from existing families: its magnitude (~2e5 m with 1e-10 m resolution) is unusual. Check zlsim against comma2k19 ECEF and orex xyz.
- Probe evidence: Directory listing of level_1b shows 197 day directories (2012_03_01 onward); the md5 manifest lists 394 kbr1c entries (asc+lbl). Day 2012_04_10 kbr1c .asc is 5,369,750 B. The label says 'Level 1B Dual-One-Way Ka-Band Ranging Data. See Table 43 in DPSIS.PDF', START 2012-101T00:00:00, STOP 2012-101T23:59:55. A 6 KB range read showed records like '387288040 221611.7100936051 -0.4874026368468322 -0.001218484839413313 0 -0.005107077777787743 2.788e-07 ...'. Range GET -r 0-0 returned 206.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_64bit/scout.20261008_162656.jsonl`).
