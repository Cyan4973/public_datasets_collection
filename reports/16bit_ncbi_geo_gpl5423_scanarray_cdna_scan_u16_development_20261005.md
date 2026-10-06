# GEO GSE23678 spruce cDNA microarray ScanArray Express raw scans uint16 development

## Outcome

Accepted `ncbi_geo_gpl5423_scanarray_cdna_scan_u16`. It is the first family of raw microarray laser-scanner images in the corpus. Each sample is one complete single-channel scan: the uncompressed 16-bit grayscale TIFF that the PerkinElmer ScanArray Express software saved for one hybridized two-colour spotted cDNA slide. The recipe emits the pixel plane unchanged as little-endian uint16.

The nearest families are:

- `ncbi_geo_mm285_methylation_idat_mean_u16`: Illumina iScan per-bead-type mean vectors. These are 1-D summaries ordered by probe ID, not images.
- `bbbc021_microscopy_tiff_u16` / `bbbc039_microscopy_tiff_u16`: widefield cell-microscopy fluorescence.

A microarray slide scan is a different instrument and scene regime: a printed spot lattice (about 180 µm pitch), a low slide background with gradients, saturated spot cores and slide edges.

## Source and rights

- **Source:** NCBI GEO series GSE23678, "Interior spruce_Bark_Leptographium abietinum_inoculation". Contributors: Kolosova, White, Ralph, Breuil, Bohlmann (UBC Michael Smith Laboratories). Platform GPL5423, Treenomix spruce 21.8K cDNA array. Public since 2012-12-01; the scans were acquired 2006-08-01 and 2006-08-03.
- **Selection:** the first 12 of the series' 36 GSM accessions in sort order (GSM572663 … GSM575585, titles hyb1 … hyb12), with both the Cy3 and the Cy5 `.tif.gz` of each: 24 files. The slides cover 6 h, 2 d and 2 w, and all three within-time-point comparison types: fungus vs control, wounding vs control, fungus vs wounding.
- **Download:** 584,061,895 bytes of `.tif.gz`, plus README.ftp and the series `filelist.txt`.
- **Pinning:** `sources.tsv` pins name, size (equal to `filelist.txt`), gzip CRC32 and ISIZE, ImageLength, TIFF DateTime and SHA-256. GEO publishes no checksums, so the hashes come from the 2026-10-05 download.
- **License:** NCBI public data (`LicenseRef-NCBI-Public-Data`). README.ftp on the serving host says "ALL DATA HERE IS PUBLIC, NON-SENSITIVE, UNRESTRICTED SCIENTIFIC DATA SHARING AMONG SCIENTIFIC COMMUNITIES", and `download.sh` re-checks that sentence on every run.
- **Rights statements:** the series matrix has no rights or restriction text. The GEO disclaimer (NCBI imposes no restrictions; submitters may claim IP) is disclosed in the manifest; it could not be fetched from this environment.
- **TIFF Copyright tag:** every file reads `Copyright (C) 2002 PerkinElmer, Inc.`. This is scanner-software boilerplate, identical in all files and predating the scans; the parser requires that exact string.
- **Precedents:** `ncbi_geo_mm285_methylation_idat_mean_u16` and `ncbi_refseq_viral_genomes_u8`.
- **Safety:** plant tissue only. The free-text TIFF tags (Artist, ProtocolDesc) are not emitted.

## Shape and conversion

Each natural record is one single-channel scan TIFF. Decoding works as follows:

1. Gunzip, with CRC32 and ISIZE checked against the pins.
2. Parse IFD0 strictly with `struct`. It must have:
   - exactly the 23 ScanArray tags and one IFD;
   - W 2200, H equal to its pin;
   - 16-bit, Compression 1, BlackIsZero, SPP 1, RowsPerStrip 1;
   - every StripByteCount 4400, with the strips tiling the pixel area up to EOF;
   - 2540 dpi;
   - Make `PerkinElmer`, Model `Express 430723`, Software `ScanArray Express 2.1.0.0`;
   - FluorName matching the dye in the file name, protocol Easy Scan, Resolution 10, LaserPower 90.
3. Concatenate the one-row strips in StripOffsets order and write the words unchanged as an `H x 2200` row-major raster.

Cy3 (543 nm laser, 570 nm filter) and Cy5 (633 nm laser, 670 nm filter) are two primary series of one family and are never interleaved. Saturated 65535 pixels and the rare zeros are native readings and stay in place. There is no missing-value code. Build and verify fail on:

- any duplicate raster;
- fewer than 1,000 distinct values;
- more than 5% zeros;
- more than 2% saturated pixels;
- more than 5% constant rows.

## Accepted output

| series | dye | samples | values | bytes | PMT gain | per-scan median DN | per-scan p99 DN | saturated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `scanarray_cy3_scan_u16` | Cy3 | 12 | 186,067,200 | 372,134,400 | 74–77 | 259–448 | 20,482–53,301 | 0.26–0.75% |
| `scanarray_cy5_scan_u16` | Cy5 | 12 | 186,067,200 | 372,134,400 | 60–62 | 191–265 | 21,600–42,348 | 0.18–0.47% |

- Primary samples: 24, with shape H x 2200 and H from 6,985 to 7,128 (15,367,000–15,681,600 values each).
- Median sample: 15,492,400 values.
- Primary values: 372,134,400.
- Primary bytes: 744,268,800.
- Distinct values per scan: 57,054–64,822. Every scan spans 0..65535.
- 1,661 zero values and 1,473,770 saturated values in total; no constant rows.
- All 24 sample hashes are distinct.
- Aggregate SHA-256 of the per-sample SHA-256s: `0ac717c806a3fbed93b14f713712be00deacfde40366efc500927316f97e7be8`.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/ncbi_geo_gpl5423_scanarray_cdna_scan_u16` passed with no warnings.
- **Verify:** I ran `verify.sh` myself. The 17-check self-test passed, a separate streaming reader re-derived all 24 rasters row by row, and the run ended with verify ok: 24 samples, 744,268,800 bytes, in 29 s.
- **Provenance timing:** the download log (19:58:51) postdates the last edits to `download.sh` (19:58:07) and `scanarray.py` (19:55). Only the sha256 column of `sources.tsv` was added afterwards, and it equals `download_plan.tsv`. I recomputed all 24 source SHA-256s myself: 0 mismatches. build.sh and verify.sh read only local files.
- **Independent byte decode:** my own minimal TIFF decoder dumped all 23 tags of hyb05 Cy5 and hyb11 Cy3. The strips are contiguous from offset 58064 to EOF, and the next IFD is 0. The concatenated strips are byte-identical to the emitted `.bin` files.
- **Width honesty:** I checked four samples (hyb01 Cy3 and Cy5, hyb09 Cy3, hyb12 Cy5):
  - code occupancy is 100% across 0–30k and 93–97% across 30k–65535;
  - the odd fraction is 0.517–0.519, so there is no widening lattice;
  - the 1.5x unevenness in the low nibble comes from the narrow background peak at 75–83 DN.
- **Structure and duplicates:**
  - The hyb04 Cy3 column-profile autocorrelation peaks at an 18 px lag, the spot lattice.
  - hyb04 Cy3 vs Cy5 correlate at r 0.770, but only 0.54% of pixels are equal: separate readings of one slide.
  - hyb04 Cy3 vs hyb06 Cy3 at the same pixel positions correlate at r 0.064: not near-duplicates.
  - zlib-6 compresses hyb04 Cy5 only 1.30x.
- **Homogeneity:** one scanner serial and software build, one protocol and one DN unit, all enforced per file. The PMT gain varies narrowly within each channel. The channels are kept as separate series.
- **Rights:**
  - I read README.ftp and fetched the GSE23678 series matrix myself; it contains no copyright, license, restriction or patent text.
  - curl and WebFetch to the GEO disclaimer page were both refused by the proxy, so the caveat stays as disclosed. The basis is identical to the accepted IDAT recipe.
  - No credentials appear in any script, and the index carries no personal fields.
- **Novelty:** `novelty.py` (series URL plus geo/samples root, with terms such as scanarray, microarray, gpl5423 and cDNA) found nothing downstream or in the registry. The only recipe neighbour is the IDAT summary-vector family. No other lab slide-scanner imagery has been accepted at 16 bits in this effort.
- **Volume:** 744 MB is about 7x the downstream need but within the cap. With 31 MB natural records it is the smallest pull that reaches about 20 samples. The download (584 MB) is smaller than the output, so this is not a thin aggregate.
