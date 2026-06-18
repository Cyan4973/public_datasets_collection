# SEC Financial Statement Data Sets 2015q1-2024q4 Numeric Values

Accepted SEC financial-statement numeric fact dataset. This uses selected
high-volume homogeneous streams from the official quarterly SEC Financial
Statement Data Sets `num.txt` tables instead of per-company companyfacts slices.

Natural sample boundary: one quarterly `num.txt` value column restricted to one
exact SEC `tag` and one exact unit (`uom`). Values are stored as little-endian
signed int64 arrays in source row order after rejecting blank, malformed,
non-integral, and out-of-range values. The build intentionally does not merge
unrelated facts just because they share a unit such as `USD` or `SHARES`.

Scope: 20 selected tag/unit streams from `2015q1` through `2024q4` (`40`
quarterly ZIP files). The realized output contains 787 primary samples; one
selected tag, `RevenueFromContractWithCustomerExcludingAssessedTax`, is absent
from `2015q1` through `2018q1`, so those empty tag/quarter streams are not
emitted as fake samples. `build.sh` rejects partial local downloads so the
realized output cannot silently fall short of the claimed 10-year scope.

Run:

```bash
SEC_USER_AGENT='openzl-public-datasets/1.0 contact=you@example.org' \
  bash datasets/sec_fsd_2015q1_2024q4_numeric_values_i64/download.sh
bash datasets/sec_fsd_2015q1_2024q4_numeric_values_i64/build.sh
bash datasets/sec_fsd_2015q1_2024q4_numeric_values_i64/verify.sh
```

SEC rejects anonymous or non-identifying automated clients. The download script
requires `SEC_USER_AGENT` with email-style contact information, stops after the
first HTTP 403 to avoid hammering a blocked client, and reuses the previously
downloaded 2024-only SEC FSD ZIPs when they are still present locally.
