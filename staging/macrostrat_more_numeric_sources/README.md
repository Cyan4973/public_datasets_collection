# Macrostrat More Numeric Sources

Candidate acquisition script for additional homogeneous Macrostrat numeric
tables. This is a staging probe, not an accepted dataset recipe.

Rationale:

- `datasets/macrostrat_units` already downloads the full units table.
- Rebuilding that payload can improve field quality, but cannot materially grow
  the dataset.
- More Macrostrat data should come from additional source tables/endpoints, with
  one homogeneous recipe per accepted material after validation.

The download script fetches exact candidate Macrostrat API endpoints and writes
`download_inventory.json` with successful resources, failures, source sizes, row
counts, and discovered numeric fields. Failed endpoints are part of the evidence
and should remain documented.

Run:

```bash
staging/macrostrat_more_numeric_sources/download.sh
```

After the run, inspect:

- `.data/downloads/macrostrat_more_numeric_sources/download_inventory.json`
- `.data/downloads/macrostrat_more_numeric_sources/download_failures.tsv`
