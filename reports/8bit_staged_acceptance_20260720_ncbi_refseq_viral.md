# 8-Bit Staged Acceptance: NCBI RefSeq Viral Genome FASTA

## Decision

Accept and promote the staged recipe `ncbi_refseq_viral_genomes_u8`.

This dataset was already downloaded, built, and benchmarked successfully in
June 2026, but it remained in `staging/` and was never promoted into
`datasets/`. The June staging cleanup later removed tracked staging files while
preserving local ignored copies, so this candidate became a successful staged
dataset rather than an accepted catalog entry.

## Catalog Fit

- Domain: curated viral nucleotide reference genomes.
- Shape: one raw sequence-letter byte sample per RefSeq viral FASTA record.
- Difference from accepted datasets: the catalog has protein alignment symbols,
  sequencing quality scores, taxonomy tables, and gene metadata, but not curated
  nucleotide genome strings as the primary numeric series.
- Numeric representation: FASTA stores sequence symbols as ASCII bytes; the
  build removes only FASTA headers and line wrapping, preserving source
  sequence-letter bytes unchanged as uint8 values.

## Materiality

The selected source is the NCBI RefSeq viral genomic FASTA release shard
`viral.1.1.genomic.fna.gz`. The recipe now requires:

- at least 1,000 FASTA records
- at least 10,000,000 primary sequence bytes
- median sample size at least 1,000 values
- non-degenerate per-record samples
- primary-output hard cap: 1,000,000,000 bytes
- download archive hard cap: 1,000,000,000 bytes

This is comfortably large enough to deserve collection while staying within the
repository's 1 GB per-dataset cap.

## Previous Candidate Rejected

`noaa_cdr_sea_ice_concentration_u8` was rejected for this pass after repeated
404 failures across the generated NOAA/NSIDC URL layouts. It should only be
revived with an exact upstream URL inventory.

## Acceptance Outcome

Accepted after user download/cache validation and local rebuild.

- Download archive: 176,358,871 bytes.
- FASTA records / primary samples: 19,433.
- Total primary values/bytes: 577,707,132.
- Sample byte-size range: 136 min / 6,864 median / 2,473,870 max.
- Same-size concentration: 0.000772.
- Build writes `role = "primary"` rows in the sample index.
