# SEC Financial Statement Data Sets 2024 Numeric Values

Accepted SEC financial-statement numeric fact dataset. This uses the official
quarterly SEC Financial Statement Data Sets `num.txt` tables instead of
per-company companyfacts slices.

Natural sample boundary: one quarterly `num.txt` value column restricted by unit
(`USD` or `shares`). Values are stored as little-endian signed int64 arrays in
source row order after rejecting blank, malformed, non-integral, and out-of-range
values.

Run:

```bash
bash datasets/sec_fsd_2024q1_q4_numeric_values_i64/download.sh
bash datasets/sec_fsd_2024q1_q4_numeric_values_i64/build.sh
bash datasets/sec_fsd_2024q1_q4_numeric_values_i64/verify.sh
```
