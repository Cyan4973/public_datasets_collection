# Zenodo Sanger ABIF Trace Int16 — Discovery

This candidate searches Zenodo metadata for Sanger sequencing chromatograms
stored as direct `.ab1` or `.abi` files. ABIF chromatograms commonly contain
four native 16-bit fluorescence-intensity arrays (`DATA9` through `DATA12`),
one for each dye channel. One channel from one sequencing read would be one
natural variable-length sample.

This would add biochemical electropherogram signals rather than another image,
audio waveform, or table-derived integer series. The intended decoder is a
small Python-standard-library ABIF parser; no Biopython installation should be
required.

The first gate is metadata and licensing only. Run:

```bash
bash staging/zenodo_sanger_abif_i16/discover.sh
```

The script downloads no chromatogram payloads. It inventories only direct ABIF
files from records carrying an explicit CC0 or CC BY license, including record
ID, DOI, filename, size, checksum, and content URL. Results are written under
`.data/discovery/zenodo_sanger_abif_i16/`.

Discovery found 92 qualified files across eight CC BY 4.0 records. The bounded
payload preflight selects 63 files from five non-clinical sources (HeLa cell
line, mouse, cane toad, cultured cell lines, and environmental bacteria) and
excludes records explicitly organized around patients or family members.

Download the pinned selection, then inspect its ABIF trace arrays:

```bash
bash datasets/zenodo_sanger_abif_i16/download.sh
bash datasets/zenodo_sanger_abif_i16/inspect.sh
bash datasets/zenodo_sanger_abif_i16/build.sh
bash datasets/zenodo_sanger_abif_i16/verify.sh
```

The downloader expects exactly 63 `.ab1` files totaling 18,119,348 bytes and
checks every Zenodo-provided MD5. The inspector does not use Biopython: it
strictly parses the big-endian ABIF header and directory, requires processed
`DATA9` through `DATA12` arrays with two-byte elements and equal lengths, and
reports per-channel value ranges, distinct counts, transitions, and zlib
ratios. It emits no training samples yet.

Build emits each complete processed dye-channel trace as one variable-length
sample. ABIF stores signed words in big-endian order; build changes only byte
order to canonical little-endian int16 and preserves every numeric value.

A later payload preflight must reject any candidate unless:

- the file has a valid ABIF container and complete directory table;
- the selected fluorescence arrays are explicitly stored as two-byte ABIF
  `short` or `word` elements;
- all four processed trace channels are present with consistent lengths;
- channel arrays are nonconstant and sufficiently large;
- the aggregate collection contains enough complete reads to be useful; and
- the record's permissive license is revalidated from pinned metadata.

Base calls, quality scores, container bytes, and arrays of other widths are not
part of the proposed 16-bit series.
