# SEC Dataset State - 2026-06-17

Current accepted SEC datasets:

- `sec_fsd_2024q1_q4_numeric_values_i64`
- `sec_submissions_largecap_bundle`

Rejected SEC shapes:

- `sec_companyfacts_*` single-metric recipes were removed because issuer-fact
  quarterly natural samples had only `32-51` values and failed the median
  natural-sample floor.
- SEC submissions single-issuer or two-issuer slices were superseded by
  `sec_submissions_largecap_bundle`.
- Local categorical filing-form remaps are not primary numeric training
  material. `sec_submission_form_code` was removed from the accepted submissions
  bundle; form strings are retained only as validation fields.

## `sec_fsd_2024q1_q4_numeric_values_i64`

- status: accepted and verified
- source: official SEC Financial Statement Data Sets quarterly ZIP files
- scope: `2024q1` through `2024q4`
- natural sample boundary: one quarterly `num.txt` value column restricted by
  unit
- primary series: `usd_value_i64`, `shares_value_i64`
- primary samples: `8`
- primary values: `11,808,107`
- primary bytes: `94,464,856`
- median primary sample values: `1,379,016.5`
- source bytes: `484,669,724`

## `sec_submissions_largecap_bundle`

- status: accepted and verified
- source: official SEC `data.sec.gov/submissions/CIK*.json` payloads
- scope: `49` tracked large-cap issuers in
  `datasets/sec_submissions_largecap_bundle/issuers.tsv`
- natural sample boundary: one issuer-column filing-metadata array
- primary series: `sec_submission_size`,
  `sec_submission_acceptance_timestamp`, `sec_submission_xbrl_flag`,
  `sec_submission_inline_xbrl_flag`, `sec_submission_filing_date_ordinal`
- primary samples: `245`
- primary values: `483,235`
- primary bytes: `1,739,646`
- median primary sample values: `1,001`

## Validation Commands

```bash
bash datasets/sec_submissions_largecap_bundle/build.sh
bash datasets/sec_submissions_largecap_bundle/verify.sh
bash datasets/sec_fsd_2024q1_q4_numeric_values_i64/verify.sh
python3 tools/audit_acceptance.py
```
