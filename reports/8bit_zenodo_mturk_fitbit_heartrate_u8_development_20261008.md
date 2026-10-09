# Fitbit intraday heart-rate uint8 development

## Outcome

Accepted `zenodo_mturk_fitbit_heartrate_u8` from the Furberg et al. crowd-sourced Fitbit exports on Zenodo (record 53894).

This is the first wearable heart-rate family in the corpus. The closest existing physiological material is `physionet_bidmc_ppg_resp_i16`, a raw 125 Hz optical pulse waveform. This recipe instead holds the device-reported heart rate as integer bpm, sampled every few seconds. zlsim measured the family as novel (OK). Its nearest family is `nihcc_chestxray14_frontal_radiograph_png_u8` at distance 0.0851.

## Source and rights

- Source: Zenodo record 53894, DOI 10.5281/zenodo.53894, published 2016-05-31 by the study authors (Furberg, Brinton, Keating, Ortiz)
- Resources:
  - `mturkfitbit_export_3.12.16-4.11.16.zip`: 20,410,739 B, MD5 `88a4396c5ff706b7eaed030de4c53588`, SHA-256 `cca5d7b1cae2370b3e1024349aa86732394129afcc84ce7b6067693ac0f4c2c6`
  - `mturkfitbit_export_4.12.16-5.12.16.zip`: 25,291,915 B, MD5 `7afbecdce29814e1be2e9a7c94f8f165`, SHA-256 `4741dfabd18453de19b6dd0a7204e8fea6e45e70bc9ddbe396956c8e4fde02f8`
- Members read:
  - `heartrate_seconds_merged.csv` in export 1: 41,069,585 B, CRC32 `b5464ae1`
  - `heartrate_seconds_merged.csv` in export 2: 89,588,303 B, CRC32 `8070fbe2`
- License: CC BY 4.0. The Zenodo record API declares `"license": {"id": "cc-by-4.0"}` for the open-access record and both files.
- Safety: the record states that thirty eligible Fitbit users consented to submitting their tracker data. Rows carry only a pseudonymous numeric export Id. The recipe emits only the bpm column, replaces Ids with ordinals p01–p15, and sets `contains_personal_data` and `contains_sensitive_data` to true. This follows the accepted PhysioNet BIDMC, UCI EMG and TCIA CMMD recipes.

## Shape and conversion

Each natural record is one participant's heart-rate readings within one export period. Rows of the Fitabase `Id,Time,Value` CSV are grouped by Id and stably sorted by the parsed naive local timestamp (`M/D/YYYY h:mm:ss AM/PM`). The integer `Value` is written unchanged as one uint8 per reading.

Processing rules:
- There is no fill value; values outside 1..255 fail the build.
- No exact duplicate rows or same-timestamp conflicts occurred.
- Each export keeps only rows inside its nominal window (2016-03-12..04-11 and 2016-04-12..05-12). This drops the 23,424 export-1 rows dated 2016-04-12, all of which are exact copies of export-2 rows.
- The two exports are never merged.
- Series under 1,000 readings are dropped: one export-1 Id with 439 rows.
- Steps, calories, METs, intensities, sleep and weight files are not read.

Sampling is irregular and gaps are not encoded:
- 26 of 27 samples follow Fitbit's 5/10/15 s intraday cadence.
- One participant (p04) reports mostly every 1–3 s.
- Export-1 heart-rate data effectively starts on 2016-03-29 to 2016-04-01, so those samples span about 11 days; export-2 samples span up to 31 days.

## Accepted output

- Source rows: 1,154,681 (export 1) and 2,483,658 (export 2)
- Heart-rate Ids: 14 per export, 15 distinct across both
- Primary samples: 27 (13 from export 1, 14 from export 2)
- Primary values: 3,614,476
- Primary bytes: 3,614,476
- Minimum sample: 2,490 values
- Median sample: 120,958 values
- Maximum sample: 285,461 values
- Value range: 36–203 bpm; 63–159 distinct values per sample
- Aggregate SHA-256 over the sorted sample payloads: `a55882b1c56947513ce453e76997e1d619c5426cb44487764b68ca40ba262101`

## Judge checks

- `gate.py staging/zenodo_mturk_fitbit_heartrate_u8`: PASS, no warnings.
- Ran `verify.sh` myself: exit 0, `verify ok samples=27 values=3614476 median=120958 min_sample=2490 max_sample=285461`. It re-derives every sample with a separate regex/dict parser and compares bytes, index fields, hashes and manifest totals.
- build.sh and verify.sh use only the local pinned zips. No network calls and no credentials in any script.
- Rights: fetched `https://zenodo.org/api/records/53894`. The license is cc-by-4.0, access is open, and file keys, sizes and MD5s equal the download.sh pins. The zips contain only Fitabase CSVs.
- Overlap: streamed both source CSVs. Export 1 has 15 dates (3/29–4/12), and all 23,424 of its 4/12 rows appear verbatim among export 2's 99,149 rows for 4/12.
- Bytes, all 27 samples:
  - means 65–98 bpm, sd 10–31
  - order-0 entropy 5.1–6.2 bits, delta entropy 1.6–3.1 bits
  - 23–61% zero deltas, fewer than 6% of deltas with |delta| >= 5
  - no zeros; the most common value is at most 6% of any sample; no duplicate payloads
- Runs: the longest constant run is 1,018 readings at 70 bpm over about 2 h (2016-04-15, p04). This is a genuine device artifact and 0.03% of the data.
- Cadence: computed per participant from the source timestamps; findings as described under Shape and conversion. p04's 1–3 s regime has the same unit and integer steps, and other participants show 1–3 s bursts too, so the family stays homogeneous.
- Novelty:
  - `novelty.py --url` (record URL, DOI, `mturkfitbit`): no matches.
  - `--terms` fitbit, heart rate, wearable, mturk, fitabase, bpm, pulse, ppg: only unrelated pulse/PPG families.
  - `--type/--instrument/--archive`: no matches.
  - Downstream registry: no heart-rate family at any width.
