# physionet_wearable_exam_stress_e4_acc_i8

Empatica E4 wristband tri-axial accelerometer recordings from PhysioNet's
[Wearable Exam Stress Dataset 1.0.0](https://physionet.org/content/wearable-exam-stress/1.0.0/)
(Amin, Wickramasuriya and Faghih, 2022, doi:10.13026/kvkb-aj90). Ten
university students wore an E4 during two midterms and a final exam.

## What is collected

- All 30 `ACC.csv` session files (S1..S10 x midterm_1, midterm_2, Final). The
  release has no other sessions.
- One sample per session: the CSV rows after the two header rows, written as
  interleaved `x,y,z` signed int8 values (`.bin`, one byte per value).
- Units are the E4's native counts of 1/64 g over a ±2 g range at 32 Hz,
  written unchanged. Gravity is included. -128 and 127 are saturation rails.
- Low-motion seated stretches are genuine and kept. Nothing is trimmed,
  filtered or resampled.

Not collected: BVP, EDA, TEMP, HR, IBI, tags, StudentGrades.txt, and the
separate PhysioNet `wearable-device-dataset`, which also uses E4 ACC and is
deliberately not merged.

## License

Open Data Commons Attribution License v1.0 (ODC-By-1.0), open access. The
release ships `LICENSE.txt`, pinned by hash. The project page states "Anyone
can access the files, as long as they conform to the terms of the specified
license. License: Open Data Commons Attribution License v1.0".
`download.sh` saves that page and checks for the statement. Cite the
dataset DOI and PhysioNet.

## Scripts

- `download.sh` fetches `SHA256SUMS.txt`, `LICENSE.txt` and the 30 `ACC.csv`
  files (137,767,322 B) from the official PhysioNet open-data S3 mirror,
  plus the project page. All files are size- and SHA-256-pinned
  (`scripts/e4acc_pins.py`) and cross-checked against `SHA256SUMS.txt`.
  It also checks the header rows and writes `download_inventory.json`.
- `build.sh` (`scripts/e4acc_build.py`) asserts three equal start times and
  a 32 Hz rate in the header rows. It then requires every data row to be
  exactly three integers in -128..127 and emits
  `samples/<id>/e4_wrist_acc_xyz_i8/S<n>_<exam>.bin`, the index
  `index/<id>/samples.jsonl`, and `filtered/<id>/ingest_stats.json`.
- `verify.sh` (`scripts/e4acc_verify.py`) re-decodes each file with an
  independent csv-module tokenizer and compares the sample bytes, every
  index field, the stats, and the manifest totals. It applies the same
  degenerate-sample rule as the build.

Both parsers self-test on a synthetic E4 file (`scripts/e4acc_synth.py`)
and on 14 corrupted variants, which they must reject.

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/physionet_wearable_exam_stress_e4_acc_i8/`.
