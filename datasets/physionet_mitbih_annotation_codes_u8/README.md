# PhysioNet MIT-BIH Annotation Codes (u8)

Candidate `uint8` recipe for the official WFDB annotation-code streams in the
MIT-BIH Arrhythmia Database.

This recipe intentionally downloads only metadata and `.atr` annotation files,
not ECG waveform samples. The natural sample is one source record's clinical
annotation-code sequence. WFDB format-control annotations are skipped; emitted
values are the official nonzero WFDB annotation type codes.

## Run

```bash
bash staging/physionet_mitbih_annotation_codes_u8/download.sh
bash staging/physionet_mitbih_annotation_codes_u8/build.sh
bash staging/physionet_mitbih_annotation_codes_u8/verify.sh
```

Optional:

- `MAX_RECORDS=12` limits download/build to the first records for a smoke test.
- `MITBIH_ANN_MIN_VALUES=1000` controls the minimum per-record annotation count.
