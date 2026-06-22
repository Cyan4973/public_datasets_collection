# GDC Simple Somatic Mutations — genomic position (per chromosome)

Genomic **start positions** of GDC simple somatic mutations (SSMs), organized as **one
family** (base-pair position) with **one sample per chromosome** — "many series of the
same physical quantity". Replaces the earlier `gdc_cases` clinical recipe, whose source
was hard-capped at ~46k values; the SSM endpoint exposes ~3.3M open-access mutations.

- Source: https://api.gdc.cancer.gov/ssms (open simple somatic mutations)
- Local raw payloads: `${DATA_DIR:-.data}/downloads/gdc_somatic_mutations/pages/`

## Families & samples

| family | quantity | type |
|---|---|---|
| `gdc_ssm_position_u32` | base-pair start position of a mutation | uint32 |

- **A sample** = one chromosome's mutation start positions, sorted ascending (canonical
  genomic order — the natural delta-codeable form for coordinates).
- **Samples/family** = number of qualifying chromosomes (autosomes 1–22 + X; those with
  `>= GDC_MIN_CHR_RECORDS` non-constant positions). The probe found 22 chromosomes with
  ≥50k mutations, so most chromosomes qualify; chrY is sparse and may drop.
- Single quantity across chromosomes (each chromosome a different length/range, same
  base-pair coordinate quantity).

## Why this and not the clinical cases

`gdc_cases` clinical fields are sparse — the densest (`age_at_diagnosis`) covers only
~46k cases, so no partition yields a large dataset. The `ssms` endpoint holds ~3.3M open
mutations, giving large per-chromosome position samples instead.

## How the crawl is bounded

INSPIRE-style sharding: one fetch loop per chromosome (a `filters` query), capped at
`GDC_MAX_PER_CHR` positions (sorted by `start_position`) so pagination depth stays modest.
Only `chromosome` + `start_position` are projected (lean payload). The build re-derives the
chromosome per record and stores positions sorted ascending.

## Run

```sh
bash datasets/gdc_somatic_mutations/download.sh   # ~240 paged JSON requests
bash datasets/gdc_somatic_mutations/build.sh
bash datasets/gdc_somatic_mutations/verify.sh
```

Tuning env vars: `GDC_MAX_PER_CHR` (default 50000), `GDC_PAGE_SIZE` (default 5000),
`GDC_MIN_CHR_RECORDS` (default 5000), `GDC_CHROMS`. Logs under
`${DATA_DIR:-.data}/logs/gdc_somatic_mutations/`.
