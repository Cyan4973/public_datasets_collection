# NIH RePORTER Projects

NIH RePORTER funded-project records, extracted into numeric field families with one
independent sample **per fiscal year**.

- Source: https://api.reporter.nih.gov/v2/projects/search (US public-domain data)
- Scope: fiscal years `NIH_START_YEAR`..`NIH_END_YEAR` (default **2010–2024**), one query per year.
- Local raw pages: `${DATA_DIR:-.data}/downloads/nih_reporter_projects/pages/`

## Family / sample structure

The RePORTER API caps `offset + limit` at **15,000** per query, so a single column
can't reach >1M. Instead each **fiscal year is an independent sample** (a cohort of
that year's funded projects), giving **≥5 natural samples per family** without mixing
regimes:

- **6 families** (each a single coherent quantity):
  - dollars (uint64): `nih_award_amount_u64`, `nih_direct_cost_amt_u64`, `nih_indirect_cost_amt_u64`
  - dates YYYYMMDD (uint32): `nih_project_start_date_u32`, `nih_project_end_date_u32`, `nih_award_notice_date_u32`
- **Samples/family**: one per fiscal year = **15** (2010–2024).
- **Sample size**: ~the first ~15,000 projects of each year (offset cap), minus rows
  missing a required field → ~11k–14k values/sample.
- `fiscal_year` is the sample axis, so it is **not** emitted as a field (it would be
  constant within a sample).

Within each year the 6 fields are atomically aligned (a project missing any required
field is dropped from all six) and de-duplicated by `appl_id`.

## Run

```sh
bash datasets/nih_reporter_projects/download.sh
bash datasets/nih_reporter_projects/build.sh
bash datasets/nih_reporter_projects/verify.sh
```

Tuning env vars: `NIH_START_YEAR`, `NIH_END_YEAR`, `NIH_LIMIT`, `NIH_WINDOW_CAP`, `NIH_REQUEST_DELAY_SECONDS`. Logs under `${DATA_DIR:-.data}/logs/nih_reporter_projects/`.
