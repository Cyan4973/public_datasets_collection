# SEC Submissions Large-Cap Bundle

Staged replacement for the weak SEC filing recipes.

Why this bundle is safe:
- same source family: `data.sec.gov/submissions`
- same material: recent filing metadata
- same generation process: one public JSON payload per issuer, same `filings.recent` table
- same row semantics for every issuer
- no mixing with companyfacts, prices, or unrelated market data

Pinned scope:
- `49` large-cap issuers
- `1000` recent filing rows per issuer where available

Selected numeric series:
- `sec_submission_form_code`
- `sec_submission_size`
- `sec_submission_acceptance_timestamp`
- `sec_submission_xbrl_flag`
- `sec_submission_inline_xbrl_flag`
- `sec_submission_filing_date_ordinal`

This is intended to replace the weak SEC submissions family survivor:
- `sec_submissions_recent`
