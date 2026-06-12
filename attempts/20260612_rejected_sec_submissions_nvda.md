# sec_submissions_nvda

- Date: 2026-06-12
- Status: rejected
- Candidate dataset: SEC submissions NVDA issuer slice
- Source: https://data.sec.gov/submissions/
- Why it looked promising: Public SEC submissions metadata with legitimate filing-size and filing-date numeric content.
- Failure class: superseded_by_homogeneous_family
- What happened: The accepted recipe was audited and found to be an unnecessarily narrow issuer-specific slice of the same material already covered by the broader accepted `sec_submissions_recent` family recipe. Keeping the NVDA-only slice as a standalone dataset added below-floor noise without adding a distinct material type.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `sec_submissions_nvda` at `5010` total values and `16032` sample bytes while `sec_submissions_recent` was already accepted at `10000` total values and covered the same SEC submissions material in a broader homogeneous recipe.
- Logs: Existing local build and verify logs for the former accepted recipe; no new acquisition failure was involved in this cleanup decision.
- Decision: Remove `sec_submissions_nvda` from `datasets/` and keep the broader `sec_submissions_recent` recipe as the accepted SEC submissions family representative.
- Retry conditions: Retry only if a future SEC submissions consolidation needs a broader multi-issuer replacement that materially improves over `sec_submissions_recent`.
