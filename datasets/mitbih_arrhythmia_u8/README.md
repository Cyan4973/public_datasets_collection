# MIT-BIH Arrhythmia ECG — 8-bit (u8)

Unsigned 8-bit ECG waveform amplitude from the MIT-BIH Arrhythmia Database, organized as
**one family per lead** with **one sample per record-lead**. Fills a local gap: the
downstream corpus has `mitbih_{mlii,v1,v2,v4,v5}_u8`, while our collection had MIT-BIH only
at 16-bit (`mitbih_arrhythmia_physionet`).

- Source: https://physionet.org/content/mitdb/1.0.0/ (48 two-lead records, 360 Hz, WFDB fmt-212)
- Local raw payload: `${DATA_DIR:-.data}/downloads/mitbih_arrhythmia_u8/`

## Families & samples

| family | lead | type |
|---|---|---|
| `mitbih_mlii_u8` | MLII | uint8 |
| `mitbih_v1_u8` | V1 | uint8 |
| `mitbih_v2_u8` / `v4` / `v5` | V2 / V4 / V5 | uint8 |

- **A sample** = one record's amplitude stream for one lead (~650,000 values, 30 min @ 360 Hz).
- WFDB format-212 packs two 12-bit signed samples per 3 bytes; each is requantized to
  unsigned 8-bit as `((s + 2048) >> 4)` (baseline → 128).
- A lead family is emitted only if **≥ 5 record-leads** qualify — MLII and V1 are present in
  most records; rarer leads (V2/V4/V5) self-drop below the floor.

## Run

```sh
bash datasets/mitbih_arrhythmia_u8/download.sh   # PhysioNet WFDB, ~100 MB
bash datasets/mitbih_arrhythmia_u8/build.sh
bash datasets/mitbih_arrhythmia_u8/verify.sh
```

Tuning env vars: `MAX_RECORDS` (limit records), `MITBIH_MIN_RECORDS` (default 1000). Logs
under `${DATA_DIR:-.data}/logs/mitbih_arrhythmia_u8/`.
