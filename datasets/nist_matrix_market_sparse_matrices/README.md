# NIST Matrix Market Sparse Matrices

Public NIST Matrix Market sparse coordinate matrices. This is a new shape for
the collection: each natural sample is a sparse coordinate-matrix attribute
array over stored entries, not a dense raster, time series, waveform, tensor, or
fixed grid.

Scope:

- source: NIST Matrix Market public sparse matrix archive
- selected format: Matrix Market `matrix coordinate` files
- pinned initial candidates: Harwell-Boeing `bcsstk01` through `bcsstk24`
- accepted matrices after validation: 19 unique matrices
- natural sample boundary: one matrix attribute array for one stored sparse matrix
- primary arrays: stored row indices, stored column indices, and stored numeric values
- symmetry policy: preserve stored Matrix Market entries exactly; do not expand symmetric matrices

The downloader uses pinned exact URLs first. Seed directory discovery remains as
a fallback, but NIST directory pages may not expose direct `.mtx.gz` links. Dead
or below-floor exact URLs are recorded and skipped; the stage fails only if no
candidate survives Matrix Market semantic validation.

Run:

```bash
bash datasets/nist_matrix_market_sparse_matrices/download.sh
bash datasets/nist_matrix_market_sparse_matrices/build.sh
bash datasets/nist_matrix_market_sparse_matrices/verify.sh
```

If the NIST directory pages change, pin exact Matrix Market URLs with:

```bash
MATRIX_MARKET_URLS_FILE=/path/to/urls.txt bash datasets/nist_matrix_market_sparse_matrices/download.sh
```

Validated local output:

- downloaded candidates retained by download validation: 21
- built unique matrices: 19
- below-entry-floor matrices: 3
- duplicate matrices skipped at build: 2
- source bytes for retained downloads: 6,282,603
- primary samples: 57
- primary values: 2,300,385
- primary bytes: 12,268,720
- primary sample value range: 1,288 / 15,100 / 219,812 min/median/max
