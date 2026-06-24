# ENA FASTQ Phred Quality Scores (uint8, per cycle)

Native **8-bit** per-base sequencing quality scores from a public ENA FASTQ run, organized
as **one family** (Phred quality) with **one sample per sequencing cycle** — "many series
of the same physical quantity". A recipe equivalent of the downstream `fastq_phred_u8`
training dataset; the values are genuine Phred quality *scores* (a numeric quantity), not
raw bytes.

- Source: https://www.ebi.ac.uk/ena — run `SRR2584863` (E. coli, Illumina 150bp, Phred+33)
- Local raw payload: `${DATA_DIR:-.data}/downloads/ena_fastq_quality_phred/reads.fastq.gz`

## Families & samples

| family | quantity | type |
|---|---|---|
| `fastq_phred_quality_u8` | per-base Phred quality score (0–~41) | uint8 |

- **A sample** = all reads' quality scores at one sequencing cycle (read position *k*).
  Quality typically declines along the read, so each cycle has a distinct distribution —
  but the quantity is identical (Phred Q), so they share one family.
- **Samples/family** = number of cycles with `>= FASTQ_MIN_CYCLE_RECORDS` values
  (≈ read length, ~150 for this run).

## Why per cycle (not per read)

Per-read quality arrays are only ~150 values — below the median floor. Transposing to
per-cycle gives ~150 large samples (one per read position), each with up to
`FASTQ_MAX_READS` values, which is both adequate and biologically meaningful.

## Run

```sh
bash datasets/ena_fastq_quality_phred/download.sh   # one gz (~183 MB), liveness-checked
bash datasets/ena_fastq_quality_phred/build.sh
bash datasets/ena_fastq_quality_phred/verify.sh
```

Tuning env vars: `ENA_FASTQ_URL` (override the run), `FASTQ_MAX_READS` (default 500000),
`FASTQ_MIN_CYCLE_RECORDS` (default 1000), `FASTQ_PHRED_OFFSET` (default 33). Logs under
`${DATA_DIR:-.data}/logs/ena_fastq_quality_phred/`.
