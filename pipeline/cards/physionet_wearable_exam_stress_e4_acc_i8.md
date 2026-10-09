# PhysioNet Wearable Exam Stress Dataset: Empatica E4 Wrist Tri-Axial Accelerometer (±2 g, 1/64 g counts, 32 Hz) Int8

- Candidate id: `physionet_wearable_exam_stress_e4_acc_i8`
- Width: int8
- Quantity: Wrist acceleration x,y,z in native E4 counts of 1/64 g (range -128..127), 32 Hz, recorded during real university exams
- Source: https://physionet.org/content/wearable-exam-stress/1.0.0/
- Resources: https://physionet.org/files/wearable-exam-stress/1.0.0/SHA256SUMS.txt, https://physionet.org/files/wearable-exam-stress/1.0.0/data/S1/Final/ACC.csv, https://physionet.org/files/wearable-exam-stress/1.0.0/LICENSE.txt
- License: ODC-By-1.0
- License evidence: https://physionet.org/content/wearable-exam-stress/1.0.0/
- License quote: Access Policy: Anyone can access the files, as long as they conform to the terms of the specified license. License: Open Data Commons Attribution License v1.0
- Natural record: One session's ACC.csv (one subject x one exam: midterm_1, midterm_2 or Final; 1.5-3 h), emitted as interleaved int8 x,y,z; the two header lines (start timestamp, 32 Hz rate) are dropped
- Estimated samples: 30
- Estimated primary values: 45,000,000
- Estimated download bytes: 137,767,322
- Estimated primary bytes: 45,000,000
- Decode path: curl each of the 30 data/S*/{midterm_1,midterm_2,Final}/ACC.csv files directly (listed in SHA256SUMS.txt, verify sha256) -> skip 2 header rows -> int() per comma field, assert -128..127 -> struct pack 'b'. Pure stdlib.
- Novelty kind: new_quantity
- Measurement type: inertial_vibration
- Instrument line: empatica_e4_wrist_accelerometer
- Archive collection: physionet.org/content/wearable-exam-stress
- Novelty evidence: novelty.py --url ... --terms empatica wrist accelerometer exam: no Empatica/E4 recipe; inertial_vibration exists only at 16/32/64 (GENEActiv i16, Bosch CISS i16, LUMO f32, etc.) with no 8-bit wrist accelerometer. The local 8-bit physiological families are MIT-BIH ECG u8, UCI EMG i8 and MHEALTH labels. The wearable-exam-stress source has no prior registry/ledger entries.
- Homogeneity: One device model (Empatica E4) with a fixed ±2 g range, 1/64 g unit and 32 Hz rate. One protocol (seated exams). All 30 sessions (10 subjects x 3 exams) are the whole natural population. Emit ACC only; BVP/EDA/TEMP are floats and different quantities.
- Risks: Seated exams give low motion; long near-constant stretches may compress very well (but the data are genuine). Modest volume (~45 MB), limited by the source. PhysioNet already has 5 autocollect acceptances, so the host-count sign-off rule may apply. An alternative with more motion is the PhysioNet wearable-device-dataset 1.0.1 (same E4 ACC, 100 shorter sessions, ODC-By), but do not combine the two.
- Probe evidence: Landing page shows Open Access and ODC-By v1.0. SHA256SUMS lists 30 ACC.csv. HEAD of all 30 returned 200 with content-lengths summing to 137,767,322 B. A 300 B range GET of S1/Final/ACC.csv shows header lines '1544027337.000000,...' and '32.000000,...' followed by integer rows like '-3,65,6'.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_182652.jsonl`).
