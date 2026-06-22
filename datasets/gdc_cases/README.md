# GDC Cancer Cases — clinical numerics (per primary site)

Clinical numeric fields from the NCI Genomic Data Commons (GDC) cancer cases, organized
as **one family per quantity** with **one sample per primary site** — "many series of the
same physical quantity". Supersedes the earlier `cases?size=500` recipe (which kept 500
cases and emitted string-length / ID series).

- Source: https://api.gdc.cancer.gov/cases (open-access clinical fields, CC0-like terms)
- Local raw payloads: `${DATA_DIR:-.data}/downloads/gdc_cases/pages/`

## Families & samples

| family | quantity | type |
|---|---|---|
| `gdc_age_at_diagnosis_days_u32` | age at diagnosis (days) | uint32 |
| `gdc_days_to_last_follow_up_i32` | days to last follow-up | int32 *(if populated)* |
| `gdc_year_of_diagnosis_u16` | calendar year of diagnosis | uint16 *(if populated)* |
| `gdc_year_of_birth_u16` | calendar year of birth | uint16 *(if populated)* |
| `gdc_days_to_death_i32` | days to death | int32 *(if populated)* |

- **A sample** = one primary site's values of a single quantity (e.g. age-at-diagnosis for
  all breast cases). **Samples/family** = number of qualifying sites (those with
  `>= GDC_MIN_SITE_RECORDS` non-constant values, default 1000). The probe found 13 sites
  with ≥1000 cases, so dense fields yield ~10–13 samples; sparse fields self-omit if < 5
  sites qualify.
- Each family is one quantity across sites; age-in-days, survival-days and calendar-years
  are never mixed.

## Why per primary site (not per project)

A liveness probe showed 13 primary sites with ≥1000 cases vs only 9 projects — so
`primary_site` is the partition that clears the per-sample floor and gives more, larger,
biologically-coherent samples. Catch-all labels (`unknown`, `not reported`) are dropped.

## Run

```sh
bash datasets/gdc_cases/download.sh   # ~25 paged JSON requests (projected, ~15 MB)
bash datasets/gdc_cases/build.sh
bash datasets/gdc_cases/verify.sh
```

The download uses `fields=` projection so the payload stays small, paginates by `from`/`size`
with a `case_id` sort for determinism, and fails fast if page 0 is empty. Families self-select,
so a GDC field-set change degrades gracefully rather than breaking the build.

Tuning env vars: `GDC_PAGE_SIZE` (default 2000), `GDC_MIN_SITE_RECORDS` (default 1000),
`GDC_FIELDS`. Logs under `${DATA_DIR:-.data}/logs/gdc_cases/`.
