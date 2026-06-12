# sec_submissions_recent

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: SEC recent submissions two-issuer bundle
- Source: https://data.sec.gov/submissions/
- Why it looked promising: Public SEC submissions metadata with legitimate filing-size, filing-date, and XBRL fields.
- Failure class: superseded_by_homogeneous_family
- What happened: The accepted recipe was audited and found to be too narrow to serve as the SEC family representative. It only covered Apple and Microsoft and only `2000` filing rows total, which made it materially weaker than a broader homogeneous large-cap SEC submissions bundle.
- Evidence: `reports/accepted_recipe_audit.tsv` previously showed `sec_submissions_recent` at `10000` total values and `20000` bytes, while the replacement `sec_submissions_largecap_bundle` now covers `49` issuers, `96647` filing rows, `579882` total values, and `1932940` sample bytes.
- Logs: Fresh local build and verify logs exist for `sec_submissions_largecap_bundle`; no new acquisition failure was involved in rejecting this narrower predecessor.
- Decision: Remove `sec_submissions_recent` from `datasets/` and replace it with the broader accepted `sec_submissions_largecap_bundle`.
- Retry conditions: None. This recipe has been superseded by a materially better homogeneous replacement.
