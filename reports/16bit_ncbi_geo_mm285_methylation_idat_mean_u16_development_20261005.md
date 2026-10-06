# GEO GSE290585 MM285 IDAT bead-type Mean uint16 development

## Outcome

Accepted `ncbi_geo_mm285_methylation_idat_mean_u16`, the first bead-array (microarray) fluorescence-intensity family in the corpus. The recipe decodes Illumina IDAT v3 files from the Infinium Mouse Methylation BeadChip (MM285, GEO platform GPL30650). It emits the native per-bead-type Mean intensities (IDAT field 104, uint16 scanner DN) unchanged, one sample per IDAT.

The nearest existing family is `encode_methylation_pct_u8`, which holds sequencing-derived CpG methylation percentages. This recipe instead preserves the raw iScan scanner summary: the mean fluorescence over the replicate beads of every bead type, in each colour channel.

## Source and rights

- Source: NCBI GEO series GSE290585, "A Ternary-code DNA Methylome Atlas of Mouse Tissues" (Zhou Lab, CHOP; PubMed 41057935); public since 2025-09-26.
- Selection: the first 75 of the series' 534 GSM accessions in ascending order (GSM8817338 to GSM8817412). Each contributes its `Grn` and its `Red` `.idat.gz`, giving 150 files on 7 BeadChips.
- Download: 400,141,383 bytes of IDAT.gz plus about 115 KB of metadata (README.ftp, filelist.txt, series matrix).
- Pinning: every file is pinned by name, size and SHA-256 in `scripts/pinned_files.tsv`. GEO publishes no checksums, so the hashes were taken from the 2026-10-05 download.
- License: NCBI public data (`LicenseRef-NCBI-Public-Data`). The NCBI FTP README on the serving host states: "ALL DATA HERE IS PUBLIC, NON-SENSITIVE, UNRESTRICTED SCIENTIFIC DATA SHARING AMONG SCIENTIFIC COMMUNITIES." `download.sh` re-checks this sentence on every run.
- The series matrix carries no restriction or IP statement.
- GEO's disclaimer (NCBI imposes no restrictions; submitters may claim IP) is disclosed in the manifest. It could not be re-fetched from this environment.
- Precedents for the same basis: `ncbi_refseq_viral_genomes_u8`, `ncbi_gene_human`, `ncbi_taxdump`, `ena_fastq_quality_phred`.
- Safety: Mus musculus (C57BL/6J) only; no personal data.

## Shape and conversion

Each natural record is one IDAT, meaning one BeadChip array position in one colour channel. Decoding works as follows:

1. Gunzip the file in memory.
2. Parse the IDAT v3 field table: magic, int64 version 3, then (uint16 code, int64 offset) entries.
3. Copy the N = 361,821 little-endian uint16 values at field 104 unchanged, in the file's ascending IlluminaID order. One IlluminaID order holds across all 150 files.

Grn and Red are two primary series of one family and are never interleaved. SD (103), NBeads (107) and IlluminaID (102) are not emitted. No background subtraction, normalization or probe-to-CpG mapping is applied.

Structural checks, all fatal on failure:

- pinned size and SHA-256, and gzip CRC;
- version 3 and N = 361,821;
- field geometry: off(103)−off(102) = 4N, off(104)−off(103) = 2N, off(107)−off(104) = 2N, MidBlock count N;
- barcode (field 402) and position (field 404) equal to the file name;
- chip type (field 403) equal to `BeadChip 12x8`;
- Grn differs from Red for every array.

A degenerate-array policy, fixed before the data was seen, is also fatal; nothing is padded or skipped.

The selection is intentionally unfiltered on chemistry: 38 bisulfite (BS) and 37 bACE arrays across 17 tissues. Conversion type and tissue are recorded per index row.

## Accepted output

| series | channel | samples | values | bytes | per-sample max | per-sample median |
| --- | --- | --- | --- | --- | --- | --- |
| `mm285_grn_bead_type_mean_u16` | Grn | 75 | 27,136,575 | 54,273,150 | 16,244–23,684 | 221–1,930 |
| `mm285_red_bead_type_mean_u16` | Red | 75 | 27,136,575 | 54,273,150 | 19,518–39,601 | 1,490–6,019 |

- Primary samples: 150, each 361,821 values (723,642 bytes); median sample 361,821 values.
- Primary values: 54,273,150.
- Primary bytes: 108,546,300.
- Distinct values per sample: 8,506–25,793.
- All 150 sample hashes are distinct.
- 21 IDATs contain 1–6 zero Means, at bead types with NBeads = 0; they are kept unchanged.
- IlluminaID order SHA-256: `9d0a2c931eeff420268dd5da518774df463c9b705bde52a90828bf87000c8ee1`.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/ncbi_geo_mm285_methylation_idat_mean_u16` passed with no warnings.
- **Verify:** I ran `bash staging/ncbi_geo_mm285_methylation_idat_mean_u16/verify.sh` myself. It reported verify_ok=1, 150 samples, 108,546,300 bytes, ranges 0..23,684 (Grn) and 0..39,601 (Red).
- **Download validators re-run locally:** `check-idats` (without `--delete-corrupt`, enforcing the pinned SHA-256s), `check-filelist` and `check-matrix` all passed. The download log (19:49) postdates the last edits to `download.sh` and the helpers; only the sha256 column of the pin list was added afterwards.
- **Selection:** I confirmed the pinned GSMs are exactly the first 75 of the 534 GSMs in `filelist.txt`.
- **Independent byte decode:** my own `struct` parser read 8 random IDATs (both channels, BS and bACE, six tissues). Each emitted `.bin` is byte-identical to field 104. SD/Mean medians of 0.23–0.39 and an NBeads median of 25 confirm the field semantics.
- **Width honesty:** low-byte entropy is 7.96–8.00 bits, the odd fraction is 0.50, and the maximum of 39,601 uses the high byte without saturating.
- **Near-duplicate check:** within a tissue, conversion and channel group, log-correlation is 0.976–0.995 (fixed probe layout), but only 0.13–0.45% of values are identical and the median relative difference is 8–23%. Correlation across conversions is 0.68 and across tissues 0.88. These are distinct natural records, not near-duplicates.
- **Homogeneity:** BS and bACE shift the Grn medians (1,113–1,930 vs 221–639) within the same DN unit, integer lattice and 0–~40k range. I judged this content variation within one instrument regime; the index metadata allows a later split.
- **Rights:** I read the local README.ftp sentence and the series matrix (public, no IP or restriction text). WebFetch and curl to the GEO disclaimer page were both refused by the proxy (403), so the submitter-IP caveat stands as disclosed. The basis is consistent with the accepted NCBI and ENA precedents. No credentials appear in any script.
- **Novelty:** `novelty.py` with the series and GEO-root URLs and the terms idat, illumina, methylation, microarray, beadchip, infinium, GSE290585 and GPL30650 found no microarray or bead-array family locally, in the registry, in the ledger or downstream. The only URL neighbor is the queued, unaccepted GPL5423 raw-scan sibling, which holds TIFF rasters.
