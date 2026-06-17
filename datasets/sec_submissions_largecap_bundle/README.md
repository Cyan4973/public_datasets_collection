# SEC Submissions Large-Cap Bundle

Accepted replacement for weak SEC filing-metadata recipes.

Why this bundle is safe:
- same source family: `data.sec.gov/submissions`
- same material: recent filing metadata
- same generation process: one public JSON payload per issuer, same `filings.recent` table
- same row semantics for every issuer
- no mixing with companyfacts, prices, or unrelated market data

Pinned scope:
- `49` large-cap issuers listed in `issuers.tsv`
- SEC `filings.recent` rows per issuer as returned by the public submissions JSON
- natural sample boundary: one issuer-column filing-metadata array

Selected numeric series:
- `sec_submission_form_code`
- `sec_submission_size`
- `sec_submission_acceptance_timestamp`
- `sec_submission_xbrl_flag`
- `sec_submission_inline_xbrl_flag`
- `sec_submission_filing_date_ordinal`

This replaces narrower SEC submissions attempts such as `sec_submissions_recent`,
`sec_submissions_nvda`, and `sec_submissions_tsla`.

Run:

```bash
bash datasets/sec_submissions_largecap_bundle/download.sh
bash datasets/sec_submissions_largecap_bundle/build.sh
bash datasets/sec_submissions_largecap_bundle/verify.sh
```
