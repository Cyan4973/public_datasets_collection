# internet_archive_metadata

- Date: 2026-06-15
- Status: rejected
- Candidate dataset: Internet Archive metadata one-page search slice
- Source: `https://archive.org/advancedsearch.php?q=collection:texts&fl[]=identifier&fl[]=downloads&fl[]=item_size&rows=100&page=1&output=json`
- Why it looked promising: Public Internet Archive item metadata with native download and item-size fields.
- Failure class: superseded_tiny_standalone
- What happened: The accepted recipe had only `200` total primary values, `1200` primary sample bytes, `2` sample rows, and median sample size `100` values.
- Why more download does not save this recipe: The source can be paginated, but a separate `internetarchive_advancedsearch` recipe already covers the same material and is the correct repair target.
- Evidence: `reports/accepted_recipe_audit.tsv` showed `internet_archive_metadata` at `200` primary values with `aggregate_floor,median_sample_floor` before removal.
- Decision: Remove `internet_archive_metadata` from `datasets/` and supersede it with the repaired `internetarchive_advancedsearch` recipe.
- Retry conditions: Do not retry this standalone ID; use `internetarchive_advancedsearch` for this material.
