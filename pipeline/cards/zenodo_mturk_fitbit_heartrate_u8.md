# Crowd-Sourced Fitbit Tracker Exports (Furberg et al., Zenodo 53894): Intraday Heart Rate (bpm, ~5 s) per Participant UInt8

- Candidate id: `zenodo_mturk_fitbit_heartrate_u8`
- Width: uint8
- Quantity: Wrist optical heart rate in beats per minute (integer, observed 49-182) at Fitbit's ~5-15 s intraday resolution
- Source: https://zenodo.org/records/53894
- Resources: https://zenodo.org/records/53894/files/mturkfitbit_export_3.12.16-4.11.16.zip?download=1, https://zenodo.org/records/53894/files/mturkfitbit_export_4.12.16-5.12.16.zip?download=1
- License: CC-BY-4.0
- License evidence: https://zenodo.org/api/records/53894
- License quote: Zenodo record metadata: "license": {"id": "cc-by-4.0"}; 'Thirty eligible Fitbit users consented to the submission of personal tracker data, including minute-level output for physical activity, heart rate, and sleep monitoring.'
- Natural record: One participant's heart-rate series within one export period (rows of heartrate_seconds_merged.csv grouped by Id, time-ordered)
- Estimated samples: 30
- Estimated primary values: 3,600,000
- Estimated download bytes: 45,702,654
- Estimated primary bytes: 3,600,000
- Decode path: curl both zips (20.4 MB + 25.3 MB) -> zipfile -> 'Fitabase Data */heartrate_seconds_merged.csv' -> csv rows Id,Time,Value -> group by Id per export, sort by parsed time -> uint8 Value (assert 0-255). Pure stdlib.
- Novelty kind: new_quantity
- Measurement type: wearable_heart_rate
- Instrument line: fitbit_wrist_optical_hr
- Archive collection: zenodo.org/records/53894
- Novelty evidence: novelty.py --url zenodo 53894 --terms fitbit 'heart rate' mturkfitbit: no recipe, registry, ledger or downstream matches (only physionet_eit 'heart rate' text). No wearable heart-rate family at any width.
- Homogeneity: Single quantity (bpm), single vendor pipeline (Fitbit intraday HR). The two export windows are consecutive months of the same cohort, so emit per (participant, export) samples. Do not mix in steps/METs/calories (different quantities, some are proxies).
- Risks: Small (~3.6 MB primary), limited by the source. A smooth, slowly varying series may land near other slow 8-bit telemetry (AEGIS OBD PIDs, OpenF1 throttle) in zlsim. Device models differ between participants (the record notes 'different types of Fitbit trackers'). Personal data was consented and is pseudonymous (numeric Id only). Irregular sampling gaps are not encoded (values only).
- Probe evidence: Zenodo API: two zips (20,410,739 B and 25,291,915 B), cc-by-4.0. Tail range GETs parsed both central directories: heartrate_seconds_merged.csv is 41,069,585 B and 89,588,303 B uncompressed. A 100 KB range of the first member inflated to rows like '2022484408,4/1/2016 7:54:00 AM,93'. 30,083 parsed values range 49..182.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_182652.jsonl`).
