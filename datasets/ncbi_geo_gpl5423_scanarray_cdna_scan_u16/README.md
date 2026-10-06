# GEO GSE23678 spruce cDNA microarray scans: PerkinElmer ScanArray Express, uint16

These are raw **laser-scanner images of two-colour spotted cDNA microarrays**.
Each sample is one complete single-channel scan of one hybridized slide: the
uncompressed 16-bit grayscale TIFF that the PerkinElmer ScanArray Express
scanner software saved, as the submitter deposited it in NCBI GEO. Pixels are
photomultiplier (PMT) intensity digital numbers at 10 µm pitch, covering the
22 mm x ~70 mm scanned slide area. That area holds the printed spot lattice of
the Treenomix 21.8K spruce cDNA array (GEO platform GPL5423), hybridized
Cy3/Cy5-labelled cDNA, slide background, saturated spot cores (65535) and the
slide edges.

Source series: **GSE23678**, *Interior spruce_Bark_Leptographium abietinum_inoculation*
(Kolosova, White, Ralph, Breuil, Bohlmann; Michael Smith Laboratories,
University of British Columbia). It has 36 hybridizations comparing
fungus-inoculated, wounded and control bark of interior spruce at 6 h, 2 days
and 2 weeks. Per the GEO scan protocol, all scans used 90% laser power, and the
PMT gains were adjusted so the two channels had a mean-intensity ratio of
about 1 and between 0% and 0.5% saturated spots.

## Scope

- **24 scans = 12 hybridizations x {Cy3, Cy5}**: the first 12 GSM accessions
  of GSE23678 in sort order (GSM572663 … GSM575585, GEO titles hyb1 … hyb12).
  Hybridizations 1–8 were scanned on 2006-08-01 and 9–12 on 2006-08-03.
- Two primary series, one per channel, never interleaved:
  - `scanarray_cy3_scan_u16`: 12 samples (543 nm laser, 570 nm filter, PMT gain 74–77)
  - `scanarray_cy5_scan_u16`: 12 samples (633 nm laser, 670 nm filter, PMT gain 60–62)
- Each sample is the whole raster, `H x 2200` uint16 in row-major order, with
  H = 6985 … 7128 depending on the scanned area (see `sample_shape` in the
  index). Samples are about 31 MB each (15.4–15.7 M values). They are neither
  tiled nor cropped.
- Totals: 372,134,400 bytes per series and **744,268,800 primary bytes**
  (372,134,400 values). The download is 584,061,895 bytes of `.tif.gz`.
- Why a subset: the full series is 72 scans (~1.75 GB gzip, ~2.2 GB decoded),
  over the 1 GB cap. Each scan is large, so 24 natural records already give
  about 7x the ~100 MB downstream selection needs while keeping a
  sample count near 20. The selection rule is mechanical (first 12 GSMs, both
  channels each). It covers all three time points and all treatment
  comparisons. The sibling pine series GSE22924 (same platform and scanner)
  is not used.

`sources.tsv` pins every file: name, size (equal to `filelist.txt` and HTTP
Content-Length), gzip trailer CRC32 and ISIZE (the exact uncompressed TIFF
size), ImageLength, TIFF DateTime, sha256 (pinned from the first full
download on 2026-10-05) and URL. `discover.sh` documents how the pins were resolved, using
only metadata requests (filelist, esummary, HEAD, 8-byte tail ranges and
128 KiB head ranges).

## Homogeneity

The recipe uses one platform (GPL5423), one lab and series, and one scanner:
Make `PerkinElmer`, Model `Express 430723`, Software `ScanArray Express,
Microarray Analysis System 2.1.0.0`. It uses one scan protocol (`Easy Scan`,
10 µm, 90% laser power) and one quantity (uint16 PMT DN, no scaling).
The parser enforces all of these for every file, and also the exact TIFF
layout. Cy3 and Cy5 share unit and process, but have different lasers,
filters, PMT gains and intensity distributions, so they are kept as two
series. The Cy3 and Cy5 scans of one slide share the spot-lattice geometry and
are spatially correlated, but they are separate physical readings, not copies.

## Conversion

1. `download.sh` runs the parser self-test, a one-byte liveness check,
   re-fetches the NCBI `README.ftp` (and requires the public-data notice) and
   the series `filelist.txt` (and requires every pinned name and size to still
   be listed). It then fetches each `.tif.gz` with resumable curl into a
   `.part` file and runs `scripts/scanarray.py check-file`. That check covers
   exact size, gzip trailer CRC32/ISIZE, the pinned sha256, a full gunzip,
   and the TIFF layout below. Only then is the file renamed into place, and
   per-file sha256 values are written to `download_plan.tsv`.
2. `build.sh` gunzips each scan and parses IFD0 with `struct`. The accepted
   layout is:
   - `II` 42, with exactly one IFD (next IFD 0) holding exactly the 23
     ScanArray tags
   - ImageWidth 2200; ImageLength equal to the pin
   - BitsPerSample 16, Compression 1, Photometric 1 (BlackIsZero),
     SamplesPerPixel 1, PlanarConfig 1, Orientation 1
   - RowsPerStrip 1, with every StripByteCount equal to 4400
   - strips tiling the pixel area with no gaps and ending exactly at EOF
   - 2540 dpi (10 µm)
   - the Make, Model, Software and Copyright strings above
   - ImageDescription with `FluorName` matching the dye in the file name,
     `Resolution=10`, `ProtocolName=Easy Scan` and `LaserPower=90`

   The 4,400-byte row strips are concatenated in StripOffsets order. The
   little-endian uint16 words are written unchanged to
   `samples/<id>/<series>/<GSM>_hybNN_<cy3|cy5>.bin`. The index rows carry
   the shape, GSM, hybridization, dye, PMT gain, laser power, scan time,
   source sha256 and value statistics.
3. `verify.sh` re-derives every sample with a separate streaming TIFF reader
   (sequential `gzip.open`, minimal tag decode). It compares the result with
   the emitted file row by row, recomputes every index statistic, and
   re-checks the manifest totals, the absence of stray files and the
   degeneracy rules.

Before every run, the parsers are self-tested on synthetic TIFFs with the same
23-tag layout. The tests cover monotone and permuted strip placement, a
streaming prefix that ends right after the strip tables, and trailing-byte
rejection. They also check that ten malformed variants are rejected: 8-bit
samples, LZW, a second IFD, wrong Make, Model, Software or Copyright, a
wrong strip size, a trailing byte, and a wrong fluor. During authoring, both
parsers agreed byte for byte on the first 46 decoded rows of all 24 real files,
read from range-fetched prefixes.

## Missing values

A scanner raster has no missing-value code. 0 (the lowest digitized reading)
and 65535 (saturation in bright spot cores) are native values and are kept in
place. Build and verify fail if a raster is duplicated, has fewer than 1,000
distinct values, more than 5% zeros, more than 2% saturated pixels, or more
than 5% constant rows.

## License and rights

- Basis: NCBI public data (`LicenseRef-NCBI-Public-Data`, the same basis as
  the accepted `ncbi_refseq_viral_genomes_u8`). The NCBI FTP README on the
  serving host says: *"NOTE: ALL DATA HERE IS PUBLIC, NON-SENSITIVE,
  UNRESTRICTED SCIENTIFIC DATA SHARING AMONG SCIENTIFIC COMMUNITIES. THESE
  SERVERS ARE INTENTIONALLY PUBLIC."* `download.sh` re-checks that sentence
  on every run.
- Caveat: GEO's disclaimer page is proxy-blocked here and its wording was
  not re-verified. As commonly quoted, it says NCBI puts no restrictions on
  use or distribution of GEO data, but submitters may claim patent, copyright
  or other IP rights that NCBI cannot assess. The GSE23678 series and sample
  records carry no rights, license or restriction statement (checked in the
  series-matrix header). The values are machine-generated scanner readings.
- **The TIFF Copyright tag is software boilerplate, not a rights claim.**
  Tag 33432 in every file reads `Copyright (C) 2002 PerkinElmer, Inc.`. The
  ScanArray Express 2.1 acquisition software writes this string into every
  image it saves. It is byte-identical in all 24 files, dated 2002 (four years
  before the 2006 scans), and names the scanner-software vendor, not the data
  producer. It does not assert rights over the measured intensities. The
  parser requires this exact string, so any other copyright text would stop
  the build for review.
- Attribution: GEO GSE23678 and its contributors (see `manifest.toml`).

## Novelty

This is a new source and a new instrument class for the corpus. No local
recipe, registry row or downstream family contains microarray scanner images
(`novelty.py` with the terms scanarray, microarray, gpl5423, laser scanner,
cy3 and cy5 matches only the ledger rows and a staging Illumina IDAT draft).
The nearest families are:
- `bbbc021_microscopy_tiff_u16` and `bbbc039_microscopy_tiff_u16`:
  widefield cell-microscopy fluorescence, a different instrument and scene
  statistics.
- The staging `ncbi_geo_mm285_methylation_idat_mean_u16` draft: per-bead-type
  mean intensity vectors from Illumina IDAT summaries, not images.

Microarray scans have a regular printed spot lattice, a low background with
slide-level gradients, saturated spot cores and dust artefacts. That makes
them a distinct 16-bit image regime.

## Caveats

- Samples are large (about 31 MB). This is the natural record; it is not
  split.
- These are 2006-era scans from one lab. All 24 share one scanner and
  software build, which keeps the regime homogeneous but limits instrument
  diversity.
- The source TIFFs also hold free-text metadata: Artist `BC Forestry
  Sciences`, `ProtocolDesc=Dr. Tai`. This is not emitted. Only PMT gain,
  laser power, fluor and scan time are copied into the index as provenance.

## Realized output (download, build and verify on 2026-10-05)

- The download took 50 s: 24 files and 584,061,895 bytes, every file passing
  `check-file`. Build and verify take about 28 s each. The gate passes with no
  warnings.
- 24 samples (12 per series), 372,134,400 values and 744,268,800 bytes. The
  median sample is 15,492,400 values and H runs from 6985 to 7128. The
  aggregate SHA-256 of the per-sample SHA-256s is
  `0ac717c806a3fbed93b14f713712be00deacfde40366efc500927316f97e7be8`.
- The 16-bit range is genuinely used. Each scan has 57,054–64,822 distinct
  values and spans 0..65535.
- Per-scan statistics by channel:

  | statistic | Cy3 | Cy5 |
  |---|---|---|
  | median DN (background-dominated) | 259–448 | 191–265 |
  | p99 DN (spots) | 20,482–53,301 | 21,600–42,348 |
  | mean DN | 1,302–2,665 | 1,193–2,087 |
  | saturated (65535) pixels | 0.26–0.75% | 0.18–0.47% |

  Overall, saturated pixels are 0.40% and zeros are 0.0004%. No scan has a
  constant row.
- Structure check on hyb1 Cy3: the column-mean profile autocorrelates most
  strongly at an 18-pixel lag (r = 0.84). That is a 180 µm spot pitch, the
  printed lattice. 29% of pixels are above 1,000 DN and 2.5% are above
  20,000 DN.
- On hyb1, the Pearson correlation between Cy3 and Cy5 (every 7th pixel) is
  0.76: same lattice, different signals.
- Compressibility on hyb1 is low, so this is high-entropy material:

  | channel | zlib -9 | xz -6 |
  |---|---|---|
  | Cy3 | 1.25x | 1.37x |
  | Cy5 | 1.33x | 1.50x |

## Commands

```bash
bash staging/ncbi_geo_gpl5423_scanarray_cdna_scan_u16/download.sh
bash staging/ncbi_geo_gpl5423_scanarray_cdna_scan_u16/build.sh
bash staging/ncbi_geo_gpl5423_scanarray_cdna_scan_u16/verify.sh
```
