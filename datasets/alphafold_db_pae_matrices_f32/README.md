# AlphaFold DB predicted-aligned-error matrices float32 discovery

This candidate targets predicted aligned error (PAE) matrices from the
AlphaFold Protein Structure Database.  A PAE value estimates, in angstroms,
the expected positional error at residue `i` when the predicted and true
structures are aligned on residue `j`.

Each retained protein would become one complete square, row-major,
little-endian float32 matrix.  PAE is directional and therefore is not assumed
to be symmetric.  The resulting shape is distinct from the accepted wwPDB
atom-coordinate streams: it is a dense residue-by-residue relationship matrix
with diagonal valleys, domain blocks, and inter-domain uncertainty.

The first stage is metadata-only:

```sh
bash datasets/alphafold_db_pae_matrices_f32/discover.sh
```

It resolves the official site's versioned application asset and validates its
explicit CC BY 4.0 statement, queries the official prediction API for a fixed
accession set spanning different organisms, folds, and sequence lengths, and
records each official PAE document URL.  It does not download any PAE matrix
payload.

Results are written under
`.data/discovery/alphafold_db_pae_matrices_f32/`, with logs under
`.data/logs/alphafold_db_pae_matrices_f32/`.

If discovery succeeds, the next stage should download the selected JSON
documents with explicit byte bounds, validate that each matrix is exactly
`sequence_length × sequence_length`, reject missing or non-finite values, and
write the source-order values as IEEE-754 little-endian float32.  The scalar
`max_predicted_aligned_error` field is metadata, not part of the matrix sample.

The corrected discovery resolves 15 unique entries across six organisms,
covering sequence lengths 103 through 1,863 and 9,238,233 projected matrix
values.  Download and validate those selected PAE documents with:

```sh
bash datasets/alphafold_db_pae_matrices_f32/download.sh
```

The downloader uses a dimension-derived cap for every JSON file.  It requires
the documented nested square matrix, exact dimensions, finite nonnegative
values, and successful IEEE-754 float32 conversion.  AlphaFold v6 declares a
maximum PAE of 31.75 while serializing saturated matrix cells as the rounded
integer 32; the validator permits only that exact ceiling case beyond the
declared maximum and records its frequency.  Exact source sizes and SHA-256
hashes are retained for the later manifest.

After the download succeeds, build and verify locally:

```sh
bash datasets/alphafold_db_pae_matrices_f32/build.sh
bash datasets/alphafold_db_pae_matrices_f32/verify.sh
```
