# ENCODE WGBS CpG Methylation Percent (uint8, per chromosome)

Native **8-bit** per-CpG DNA methylation level (percent, 0–100) from a public ENCODE
whole-genome bisulfite sequencing (WGBS) bedMethyl file, organized as **one family** with
**one sample per chromosome** — "many series of the same physical quantity". A novel
epigenetic numerical quantity not previously in the corpus.

- Source: https://www.encodeproject.org/ — file `ENCFF424XKF` (WGBS, GRCh38)
- Local raw payload: `${DATA_DIR:-.data}/downloads/encode_methylation_pct_u8/methylation.bed.gz`

## Families & samples

| family | quantity | type |
|---|---|---|
| `methylation_pct_u8` | per-CpG methylation level (percent, 0–100) | uint8 |

- **A sample** = all covered CpGs' methylation percentages on one chromosome.
- **Samples/family** = number of chromosomes with `>= METH_MIN_CHR_RECORDS` covered CpGs
  (autosomes 1–22 + X, typically ~23).
- Covered CpGs only: bedMethyl pads uncovered sites with `0`, which are not measurements —
  we keep `coverage >= METH_MIN_COVERAGE` (default 1).

## Why one ~595 MB download

bedMethyl is genome-wide WGBS (~28M CpGs); ENCODE offers no small RRBS equivalent for this
assembly. ENCODE serves from a fast CDN (the `@@download` URL 307-redirects to S3/Azure),
and the download is resumable, so the size is manageable. We keep ~tens of millions of real
methylation values.

## Run

```sh
bash datasets/encode_methylation_pct_u8/download.sh   # ~595 MB gz, resumable, redirect-following
bash datasets/encode_methylation_pct_u8/build.sh
bash datasets/encode_methylation_pct_u8/verify.sh
```

Tuning env vars: `ENCODE_METH_URL` (override the file), `METH_MIN_COVERAGE` (default 1),
`METH_MIN_CHR_RECORDS` (default 1000). Logs under
`${DATA_DIR:-.data}/logs/encode_methylation_pct_u8/`.
