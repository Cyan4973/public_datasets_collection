# SEC Companyfacts NetIncomeLoss Quarterly

This recipe downloads SEC companyfacts JSON for a fixed five-company subset and emits one quarterly net income sample per company.

Selected companies:
- `apple`
- `microsoft`
- `alphabet`
- `amazon`
- `meta`

Generated series:
- `net_income_i64`
- `obs_year_u16`

Missing-value policy:
- filter facts missing `fy`, `fp`, or `val`
- filter facts whose `fp` is not one of `Q1`..`Q4`
- filter facts whose value is not an integral numeric dollar amount
- filter facts with years outside `1900..2100`
- when multiple facts map to the same fiscal year and quarter, keep the one with the lexicographically latest `end` then `filed` values

Run:

```sh
bash datasets/sec_companyfacts_net_income_quarterly/download.sh
bash datasets/sec_companyfacts_net_income_quarterly/build.sh
bash datasets/sec_companyfacts_net_income_quarterly/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/sec_companyfacts_net_income_quarterly/`.
