# SEC Companyfacts Single-Metric Recipes

Removed from `datasets/` on 2026-06-17:

- `sec_companyfacts_assets_quarterly`
- `sec_companyfacts_cash_and_equivalents_quarterly`
- `sec_companyfacts_net_income_quarterly`
- `sec_companyfacts_operating_income_quarterly`
- `sec_companyfacts_stockholders_equity_quarterly`

Reason: each accepted recipe contained only five issuer-level quarterly samples
with `227` total primary values, `1,816` primary bytes, and median natural sample
size `51` values. These fail the aggregate and median-sample floors.

Repair assessment: adding more issuers or more single metrics would only
multiply tiny issuer-fact quarterly natural samples and would not repair the
median natural-sample floor. A multi-metric companyfacts bundle was also
rejected in the 64-bit unfinished audit for the same reason.

Replacement: keep `sec_fsd_2024q1_q4_numeric_values_i64` as the SEC financial
statement numeric fact representative. It uses official SEC Financial Statement
Data Sets quarterly `num.txt` tables and validated at `11,808,107` primary
values and `94,464,856` primary bytes.
