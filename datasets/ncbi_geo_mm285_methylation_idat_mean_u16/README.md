# GEO GSE290585 MM285 IDAT bead-type Mean intensities (uint16)

Native 16-bit per-bead-type mean fluorescence intensities from Illumina
Infinium Mouse Methylation BeadChip (MM285, GEO platform GPL30650) IDAT files.
The source is GEO series GSE290585, "A Ternary-code DNA Methylome Atlas of
Mouse Tissues" (Zhou Lab, Children's Hospital of Philadelphia; PubMed
41057935).

Each IDAT file is the iScan scanner summary of one BeadChip array position in
one color channel. Field 104 (`Mean`) holds one little-endian uint16 per bead
type: the mean intensity, in scanner digital numbers, over that bead type's
replicate beads. Every IDAT here has N = 361,821 bead types. Values run from
background (tens to hundreds) to bright probes (tens of thousands). This is
raw instrument output: nothing is background-corrected, normalized, or mapped
to CpGs.

## Scope

- Selection: the first 75 GSM accessions of GSE290585 in ascending numeric
  order (GSM8817338 to GSM8817412). Each contributes its `Grn` and its `Red`
  `.idat.gz`, for 150 files on 7 BeadChips. Names and sizes are pinned in
  `scripts/pinned_files.tsv`, generated from the series `filelist.txt` by
  `scripts/make_pins.py`.
- Download: 400,141,383 bytes of IDAT.gz plus about 115 KB of metadata
  (`README.ftp`, `filelist.txt`, series matrix). The full series is 1,068
  IDATs and 2.85 GB, which is deliberately not collected.
- Output: 150 samples of 361,821 uint16 values each (723,642 bytes per
  sample), 108,546,300 primary bytes in total.

| series | channel | samples | bytes |
| --- | --- | --- | --- |
| `mm285_grn_bead_type_mean_u16` | Grn (Cy3 scan) | 75 | 54,273,150 |
| `mm285_red_bead_type_mean_u16` | Red (Cy5 scan) | 75 | 54,273,150 |

One IDAT is one sample: one array position in one channel. Grn and Red are
two primary series of one family. They share the instrument, unit, bead
layout and generation process, but their intensity distributions differ (in
the probe pair GSM8817338, Grn median 1,416 and max 17,057; Red median 2,359
and max 26,109). The channels are never interleaved or merged.

## Sample heterogeneity, kept on purpose

The atlas profiles each DNA sample twice: once after standard bisulfite
conversion (`BS`) and once after bACE conversion, which reads 5hmC. The
selected GSMs are 38 BS and 37 bACE arrays across 17 tissues. The conversion
chemistry changes which probes light up (biology). It does not change the
scanner, the unit, or the bead layout (instrument physics). The recipe does
not filter on conversion type. Each index row records
`cytosine_conversion_type` and `tissue` from the series matrix as metadata.

## Rights

- The NCBI FTP README on the same host says: "NOTE: ALL DATA HERE IS PUBLIC,
  NON-SENSITIVE, UNRESTRICTED SCIENTIFIC DATA SHARING AMONG SCIENTIFIC
  COMMUNITIES. THESE SERVERS ARE INTENTIONALLY PUBLIC." `download.sh`
  re-fetches `README.ftp` on every run and fails if that sentence is gone.
- Caveat: GEO's disclaimer page is proxy-blocked here, so its wording was not
  re-checked in this session. It says NCBI places no restrictions on the use
  or distribution of GEO data, but submitters may claim patent, copyright or
  other IP rights in what they submit. No such claim is attached to
  GSE290585, and the payload is machine-generated scanner intensities.
- Precedents for this NCBI public-data basis: `ncbi_refseq_viral_genomes_u8`
  (`LicenseRef-NCBI-Public-Data`) and `ena_fastq_quality_phred`.
- Mouse tissue only (C57BL/6J, checked per GSM against the series matrix). No
  human or personal data.

## IDAT v3 decoding (pure standard library)

The file starts with `IDAT`, then an int64 version (3), an int32 field count,
and a table of (uint16 code, int64 offset) entries. The fields used are:

| code | content |
| --- | --- |
| 1000 | int32 N |
| 102 | N int32 IlluminaIDs (ascending) |
| 103 | N uint16 SD |
| 104 | N uint16 Mean (the payload) |
| 107 | N uint8 NBeads |
| 200 | int32-counted MidBlock |
| 402 | chip barcode string |
| 403 | chip type (`BeadChip 12x8`) |
| 404 | array position (`R01C01`) |

Strings use .NET 7-bit length prefixes. Note: the position string is field
404. Field 403 is the chip type.

## Validation

`download.sh` runs these checks, then fails and logs if any of them fails:

- the parser self-test on synthetic IDATs;
- the README.ftp public-data sentence;
- every pinned (name, size) pair present in `filelist.txt`;
- the series matrix: GSE290585, GPL30650, *Mus musculus*, and exactly the
  pinned Grn/Red names for each GSM;
- per file: pinned size and SHA-256, gzip CRC, magic, version 3, N = 361,821,
  `off(103)-off(102) = 4N`, `off(104)-off(103) = 2N`,
  `off(107)-off(104) = 2N`, MidBlock count N, barcode and position equal to
  the file name, and chip type;
- one IlluminaID order shared by all 150 files;
- Grn differs from Red for every array.

Files with corrupt gzip data or a mismatched pinned hash are deleted so a
re-run refetches them. Transfers use `curl -fL -C -` with stall-based limits
(`--speed-limit 1024 --speed-time 120`), never `--max-time`.

`build.sh` repeats the structural checks and applies the degenerate-array
policy, which is fatal; arrays are never padded or skipped. A sample is
degenerate when any of these holds:

- fewer than 2,000 distinct values;
- zero Means for more than 0.1% of N;
- p01 above 1,500 (no background floor);
- median below 200;
- p99 below 3,000 or max below 10,000 (no bright probes);
- NBeads = 0 for more than 1% of N.

`verify.sh` (`scripts/verify_mm285.py`) shares no code with the build. It
re-decodes every IDAT and requires each sample to be byte-identical to field
104. It recomputes the statistics by sorting and re-applies the same
thresholds. It also checks the index, an exact sample-directory inventory,
the manifest totals, and that each series spans background (<1,000) to
bright (>=10,000).

## Files

- `download.sh`, `build.sh`, `verify.sh`: script contract, with logs under
  `$DATA_DIR/logs/ncbi_geo_mm285_methylation_idat_mean_u16/`.
- `scripts/mm285_idat.py`: IDAT decoder, validators, build, and `selftest`.
- `scripts/verify_mm285.py`: independent verifier.
- `scripts/make_pins.py`, `scripts/pinned_files.tsv`: the pinned selection.
  GEO publishes no checksums, so the `sha256` column was filled from the
  2026-10-05 download with `make_pins.py <filelist> <tsv> <idat_dir>`. The
  GSM8817338 Grn hash also matches an earlier, independent probe fetch. All
  three scripts enforce the column.

## Realized output (2026-10-05 build)

| | Grn | Red |
| --- | --- | --- |
| samples | 75 | 75 |
| per-sample max | 16,244 to 23,684 | 19,518 to 39,601 |
| per-sample median | 221 to 1,930 | 1,490 to 6,019 |
| distinct values per sample | 8,506 to 12,492 | 11,862 to 25,793 |

- All 150 sample hashes are distinct. A single IlluminaID order holds across
  all files (sha256 `9d0a2c93…`).
- Zero Means: 21 IDATs contain 1 to 6 of them, essentially all at bead types
  with NBeads = 0, meaning no bead decoded on that array. They are kept.
- BS vs bACE: the conversion chemistry visibly shifts the green channel. Grn
  medians are 1,113 to 1,930 on BS arrays and 221 to 639 on bACE arrays. Red
  medians are 1,490 to 3,926 on BS and 2,321 to 6,019 on bACE. The unit,
  integer lattice and value range (0 to about 40,000) are shared, so both are
  kept.
- The degenerate thresholds were fixed before the data was seen. The lowest
  bACE Grn median (221) sits close to the median >= 200 dead-array threshold.
  Since every file is hash-pinned, the build is deterministic.
