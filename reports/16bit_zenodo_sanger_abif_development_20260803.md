# Zenodo Sanger ABIF Int16 Development — 2026-08-03

`zenodo_sanger_abif_i16` adds native signed-16-bit biochemical detector
signals: processed fluorescence electropherograms from Sanger DNA sequencing.
This generation process and variable-length four-dye trace structure are
distinct from the corpus's audio, electrophysiology, RF, image, and tabular
16-bit families.

## Discovery, license, and source selection

Metadata-only Zenodo discovery examined 77 records and found 92 direct `.ab1`
files across eight records with explicit CC BY 4.0 metadata. The accepted
bounded subset contains 63 files totaling 18,119,348 source bytes from five
immutable record IDs:

- `10829882`: 14 HeLa PINK1 cell-line chromatograms;
- `14001236`: 2 mouse Prex2 verification chromatograms;
- `15945185`: 38 cane-toad CRISPR chromatograms;
- `17172684`: 6 environmental bacterial 16S chromatograms; and
- `7840070`: 3 cultured-cell-line methylation chromatograms.

All five records declare CC BY 4.0. The downloader revalidates record identity,
license, exact file counts and byte totals, and every Zenodo-provided MD5.
Three otherwise qualified records organized around patients or family members
were deliberately excluded. The emitted samples contain no base calls,
identifiers, quality scores, or clinical records.

## Native representation

Every source is a valid big-endian ABIF v1.x container. The strict
standard-library parser validates the root directory, used entry count,
bounded zero padding, tag uniqueness, and all payload bounds. Each file has
processed `DATA9`, `DATA10`, `DATA11`, and `DATA12` arrays with:

- ABIF element type `short`;
- two bytes per element;
- equal channel lengths within the chromatogram; and
- nonconstant signed-int16 values.

Each complete dye channel is one natural one-dimensional sample. Build changes
only byte order from source big-endian to canonical little-endian int16. It
does not scale, clip, smooth, baseline-correct, truncate, or concatenate
traces.

## Verified output

The accepted family contains:

- 63 source chromatograms;
- 252 complete channel samples;
- 3,050,572 values and 6,101,144 primary bytes;
- 57 distinct sample lengths, ranging from 4,602 to 32,767 values;
- stored values spanning 0 through 6,749; and
- 129 to 914 distinct values per sample.

Per-sample zlib-9 ratios range from `0.056658` to `0.609836`, with median
`0.462583`, confirming useful local structure rather than noise-like data.
Build and verification pass. Verification reparses and rechecks all source
containers and MD5s, independently reconstructs every little-endian trace,
byte-compares all 252 outputs, validates hashes and index metadata, and rejects
missing or extra sample files.
