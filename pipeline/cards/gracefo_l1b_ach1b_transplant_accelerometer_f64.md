# GRACE-FO Level-1B (JPL RL04) Hybrid-Transplant Accelerometer ACH1B 1 Hz Non-Gravitational Linear Accelerations, 2023 Q1, Float64

- Candidate id: `gracefo_l1b_ach1b_transplant_accelerometer_f64`
- Width: float64
- Quantity: 1 Hz non-gravitational linear acceleration of a GRACE-FO spacecraft in the science reference frame: lin_accl_x, y and z in m/s². Values are about 1e-7 to 1e-5 m/s² and are printed with 16 significant digits.
- Source: https://isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04/
- Resources: https://isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04/2023/, https://isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04/2023/gracefo_1B_2023-01-01_RL04.ascii.ACX.tgz, https://isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04/README, https://podaac.jpl.nasa.gov/dataset/GRACEFO_L1B_ASCII_GRAV_JPL_RL04
- License: NASA Earth Science / SMD open data policy, declared in every file's YAML header (license: https://science.nasa.gov/earth-science/earth-science-data/data-information-policy). The JPL-produced product is mirrored by GFZ ISDC.
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: File header of ACH1B_2023-01-01_D_04.txt: 'license: https://science.nasa.gov/earth-science/earth-science-data/data-information-policy' and 'acknowledgement: GRACE-FO is a joint mission of the US National Aeronautics and Space Administration and the German Research Center for Geosciences. Use the digital object identifier provided in the id attribute when citing this data.' NASA SMD policy: 'information produced from SMD-funded scientific research activities be made publicly available.'
- Natural record: One daily ACH1B_YYYY-MM-DD_D_04.txt member of the daily ACX tarball: 86,400 records x 3 axes, stored as a [records,3] float64 array. Each tarball also holds ACU1B (an updated transplant, a near-duplicate product) and AC01B/AC11B (thruster-model versions). Do NOT bundle those; take ACH1B only.
- Estimated samples: 90
- Estimated primary values: 23,300,000
- Estimated download bytes: 1,010,000,000
- Estimated primary bytes: 187,000,000
- Decode path: curl the daily .ascii.ACX.tgz (about 11 MB). Python tarfile+gzip extracts the ACH1B member, skips the YAML header up to '# End of YAML header', then reads columns 3-5 (lin_accl_x/y/z) with float() into '<d'. Columns 6-8 (ang_accl) are all zero and must be excluded. The acl_*_res residual columns are optional auxiliaries. Verify the 'checksum' member. Pure stdlib.
- Novelty kind: new_modality
- Measurement type: spaceborne_accelerometer
- Instrument line: gracefo_superstar_accelerometer_hybrid_transplant
- Archive collection: isdc-data.gfz.de/grace-fo/Level-1B
- Novelty evidence: novelty.py --url https://isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04/: same host only (gfz_gracefo_fgm_acal_bnec_f64, which is a different product: GFZ magnetometer CDF from MAGNETIC_FIELD/). Accelerometer term matches are terrestrial or IMU (monado Valve Index 1 kHz IMU, LUMO tower, honeybee PCM16). An electrostatic space accelerometer measuring 1e-7 m/s² drag/SRP signals at 1 Hz is not represented. The inertial_vibration members are high-rate vibration or IMU material.
- Homogeneity: One product (ACH1B, 'GRACE-FO Level-1B Hybrid Transplant Accelerometer Data'), one satellite file type (D), one release (RL04), one cadence (1 Hz), one unit (m/s²), and one contiguous window (2023-01-01..2023-03-31, all inside the ACX-only period before ACX2 appeared). Axis scales differ (y bias about 1.07e-5 vs x/z about 1e-7). That is intrinsic to one vector record, like IMU xyz.
- Risks: Transplant/hybrid products are derived L1B (official, stable, machine-facing). The judge should accept them as a pinned operational product, not a local invention. Extraction ratio is about 18% (11 MB tgz for 2 MB kept) because the tarball also carries ACU1B/AC01B/AC11B. Acceptable, but do not add those as extra samples, because ACU1B nearly duplicates ACH1B. This would be the second GFZ ISDC acceptance this effort (OK; a third would need sign-off). Confirm ACH1B is present in every Q1 2023 tarball; it was verified for 2023-01-01 only. Possible compression closeness to gfz_gracefo_fgm B_NEC (also 1 Hz xyz f64), though magnitudes differ by about 11 orders.
- Probe evidence: Year listings: ACX tarballs for 2019=365, 2022=365, 2023=365 (ACX2 243), 2024 ACX=152, 2025 only ACX2. Downloaded one 11 MB ACX tgz for 2023-01-01. Members: AC01B C/D, AC11B C/D, ACH1B_D (13,986,603 B), ACU1B_D, checksum. ACH1B has 86,400 rows. Columns 3-5 are non-zero full precision (e.g. 1.433859730278667e-07, 1.075182061782305e-05, -1.709827351769547e-07); columns 6-8 are all zero. Header title 'GRACE-FO Level-1B Hybrid Transplant Accelerometer Data', with the license URL as quoted. Range GET on the 2023-02-01 ACX tgz returned 206.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_64bit/scout.20261008_162656.jsonl`).
