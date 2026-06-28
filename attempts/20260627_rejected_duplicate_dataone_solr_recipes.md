# Duplicate DataONE Solr Recipes

- Date: 2026-06-27
- Status: rejected
- Candidate datasets: `dataone_solr_1000`, `dataone_solr_large_retry`
- Source: DataONE public Solr API
- Failure class: below_floor; duplicate one-page slices
- What happened: both recipes queried the same DataONE Solr corpus as
  `dataone_solr` with a fixed 1000-row page. They emitted small slices and
  duplicated the same material rather than defining distinct dataset families.
- Evidence: `reports/accepted_recipe_audit.tsv` classified all three DataONE
  Solr recipes as below floor before repair. `dataone_solr` and
  `dataone_solr_large_retry` used the same `q=*:*&rows=1000&wt=json` query;
  `dataone_solr_1000` was a narrower field projection of the same first page.
- Decision: keep `dataone_solr` as the canonical DataONE Solr recipe and
  repair it with stable `start` pagination. Remove the two duplicate accepted
  recipe directories.
- Retry conditions: only restore a separate DataONE recipe if it targets a
  materially different, coherent Solr query family with homogeneous numeric
  series and enough records to pass current floors.
