# BAM Read Mapping Quality (uint8)

Collects native 8-bit **MAPQ** (mapping quality) scores from public BAM
sequencing alignments — the Phred-scaled probability that a whole read is mapped
to the wrong location. MAPQ is a native `uint8` field of every BAM alignment
record (typically 0–60 for BWA), and it is a genuinely different quantity from
per-base call quality (`ena_fastq_quality_phred`): read-level alignment
confidence vs. base-level call quality.

One homogeneous family (`bam_read_mapq_u8`); the natural sample boundary is one
source BAM's read set → **one sample per BAM**.

```bash
datasets/bam_read_mapq_u8/download.sh
datasets/bam_read_mapq_u8/build.sh
datasets/bam_read_mapq_u8/verify.sh
```

## Bounded download

BAMs are multi-GB, so `download.sh` fetches only a bounded **byte-range prefix**
(default ~48 MB) of each source BAM — a whole number of leading BGZF blocks — and
the build extracts MAPQ from the reads in that prefix. Note the download-to-output
ratio is high: MAPQ is 1 byte per ~200–450-byte record, so ~48 MB of BAM yields a
few hundred KB of MAPQ. The absolute download stays modest (default ~6 BAMs ×
48 MB ≈ 290 MB) for a genuine multi-sample per-read family (~millions of values).

The default sources are 1000 Genomes phase-3 low-coverage **BWA** alignments (all
one aligner, so MAPQ shares the 0–60 scale = homogeneous). Upstream filenames can
change; if any default 404s, supply your own list:

```bash
BAM_URLS_FILE=/path/to/bam_urls.txt datasets/bam_read_mapq_u8/download.sh
```

`bam_urls.txt` is one BAM URL per line (or `name<TAB>url`). Any coordinate- or
name-sorted BAM works; keep to a single aligner for a homogeneous family.

## Parsing (no external tools)

Pure-python, stdlib only (no samtools/pysam): BGZF blocks are concatenated gzip
members decoded with `zlib`; each BAM record's MAPQ is read from a fixed byte
offset. Only complete leading BGZF blocks and complete records are used — the
truncated tail of the prefix is dropped.

Tunables (all optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `BAM_MAX_BYTES` | `48000000` | Per-BAM byte-range prefix cap |
| `BAM_URLS_FILE` | — | Newline/TSV list of BAM URLs (overrides defaults) |
| `BAM_MIN_READS_PER_SAMPLE` | `10000` | Minimum reads for a BAM to become a sample |
| `BAM_MIN_SAMPLE_COUNT` | `5` | Minimum BAM samples for the build to succeed |

Only numeric MAPQ values are extracted — no sequence, read names, or identifiers.
