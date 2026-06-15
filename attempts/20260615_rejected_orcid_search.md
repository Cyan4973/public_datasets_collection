# orcid_search

- Date: 2026-06-15
- Status: rejected
- Candidate dataset: ORCID search for Stanford affiliation
- Source: `https://pub.orcid.org/v3.0/search/?q=affiliation-org-name:stanford&rows=100`
- Why it looked promising: Public researcher identifier search with structured ORCID identifiers.
- Failure class: intrinsically_small_standalone
- What happened: The accepted recipe had only `390` total primary values, `780` primary sample bytes, `4` sample rows, and median sample size `100` values.
- Why more download does not save this recipe: The affiliation query is arbitrary, and the numeric payload is mostly identifier chunks rather than meaningful source measurements.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `orcid_search` at `390` primary values with `aggregate_floor,median_sample_floor` before removal.
- Decision: Remove `orcid_search` from `datasets/` and reject this standalone recipe shape.
- Retry conditions: Retry only as a materially different ORCID recipe with meaningful native numeric metadata and a coherent broad scope.
