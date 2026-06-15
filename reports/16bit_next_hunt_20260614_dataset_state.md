# 16-bit Next Hunt Dataset State

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

| dataset_id | status | primary samples | primary bytes | sample geometry | min / p10 / p25 / median / p75 / p90 / max sample bytes | unique sizes | same-size fraction | reasons |
|---|---:|---:|---:|---|---|---:|---:|---|
| `dwd_radolan_rw_precip_i16` | `ok` | 192 | 311040000 | 2D raster 900x900 | 1620000 / 1620000 / 1620000 / 1620000 / 1620000 / 1620000 / 1620000 | 1 | 1.000000 | none |
| `nsynth_test_notes_i16` | `ok` | 4096 | 524288000 | 1D waveform 64000 frames @ 16000 Hz | 128000 / 128000 / 128000 / 128000 / 128000 / 128000 / 128000 | 1 | 1.000000 | none |
