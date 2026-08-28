# AlphaFold DB predicted-aligned-error float32 development

## Outcome

Accepted `alphafold_db_pae_matrices_f32` as a new two-dimensional num32
family.  It contains 15 complete directional residue-by-residue predicted
aligned error (PAE) matrices with 9,238,233 values and 36,952,932 bytes of
little-endian float32 output.

This shape is distinct from the existing wwPDB atom-coordinate streams.  Each
sample is a dense square relationship matrix rather than a point list: rows
identify the residue whose position is scored, columns identify the residue
used for structural alignment, and the matrix contains diagonal valleys,
protein-domain blocks, and asymmetric inter-domain uncertainty.

## License and source validation

The official AlphaFold DB web application asset explicitly states
`CC-BY-4.0` and requests attribution.  The exact 312,610-byte versioned asset
was pinned by SHA-256.  Fifteen exact versioned PAE JSON documents were also
pinned by URL, source size, SHA-256, accession, entry ID, model version,
sequence length, and declared maximum.

The selection spans six organisms and protein lengths from 103 through 1,863
residues.  One obsolete accession request returned 404 and was excluded.  The
API's broader search results also exposed an unrelated numeric-ID result for
one accession; discovery was corrected to prefer the exact canonical
`AF-<accession>-F1` entry and otherwise require one uniquely annotated exact
accession result.

## Numeric validation

Every source document contains one complete square matrix whose dimensions
exactly equal the selected sequence length.  All values are numeric, finite,
nonnegative, nonconstant, and convertible to IEEE-754 binary32.

Fourteen v6 matrices are integer-quantized and contain 26 to 33 distinct
values.  Their diagonal is exactly zero.  AlphaFold declares a maximum PAE of
31.75 while three saturated p53 cells are serialized as the rounded integer
32; the parser permits only this exact integer ceiling case.  The selected
numeric-ID v1 SARS-CoV-2 spike matrix retains 2,521 distinct decimal values,
has a 0.25 diagonal, and declares a maximum of 31.55.

All matrices are measurably directional rather than symmetric.  The complete
source JSON set occupies 30,904,585 bytes; deterministic row-major float32
conversion produces 36,952,932 bytes.

## Build and verification

The build emits one natural rank-2 sample per protein with axes
`scored_residue_i × alignment_residue_j`.  It excludes sequences, coordinate
models, scalar maxima, API records, and JSON framing.  No matrices are joined,
split, transposed, normalized, or imputed.

Verification independently reparsed all 15 JSON documents, reconstructed each
little-endian float32 matrix, compared every output byte, checked the complete
file and index inventories, and reproduced all aggregate statistics.
