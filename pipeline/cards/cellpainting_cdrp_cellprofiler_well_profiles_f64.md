# Cell Painting Gallery cpg0012 (Wawer/Bray CDRP bioactive-compound screen): CellProfiler Per-Well Morphological Profiles (Cells/Cytoplasm/Nuclei/Image features), Float64

- Candidate id: `cellpainting_cdrp_cellprofiler_well_profiles_f64`
- Width: float64
- Quantity: Per-well aggregated CellProfiler measurements from a 5-channel Cell Painting assay (U2OS cells; DNA/ER/RNA/AGP/Mito): about 4,716 morphology, intensity, texture, granularity, radial-distribution and correlation features per well. The values are full-precision doubles (17 significant digits, e.g. 0.9714556719755841) written by cytominer aggregation of the per-cell CellProfiler SQLite backend.
- Source: https://registry.opendata.aws/cellpainting-gallery/
- Resources: https://cellpainting-gallery.s3.amazonaws.com/?list-type=2&prefix=cpg0012-wawer-bioactivecompoundprofiling/broad/workspace/backend/CDRP/, https://cellpainting-gallery.s3.amazonaws.com/cpg0012-wawer-bioactivecompoundprofiling/broad/workspace/backend/CDRP/24277/24277.csv, https://github.com/broadinstitute/cellpainting-gallery
- License: CC0-1.0
- License evidence: https://registry.opendata.aws/cellpainting-gallery/
- License quote: License: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication, but please do cite the corresponding publication for each dataset
- Natural record: One 384-well assay plate: the backend/CDRP/<plate>/<plate>.csv matrix of wells x feature columns. Drop the 9 Metadata_* columns (plate/well IDs and object counts are proxies) and keep the Cells_*/Cytoplasm_*/Nuclei_*/Image_* feature columns in source row and column order. Do NOT use the 8 GB per-plate .sqlite files.
- Estimated samples: 30
- Estimated primary values: 54,300,000
- Estimated download bytes: 1,030,000,000
- Estimated primary bytes: 435,000,000
- Decode path: curl the per-plate CSVs (about 34 MB each) from the anonymous public S3 bucket. Python csv module: the header gives 4,725 columns; skip the Metadata_* columns, float() every remaining cell, and pack little-endian float64 with struct, one .bin per plate. Empty or NaN cells need a declared policy (none seen in the probed row). Stdlib only.
- Novelty kind: new_modality
- Measurement type: cell_morphology_profile
- Instrument line: Broad Institute Cell Painting (5-channel widefield HCS) + CellProfiler/cytominer
- Archive collection: aws_cellpainting_gallery
- Novelty evidence: novelty.py --url on the cpg0012 backend prefix and --terms cellprofiler / 'cell painting' / morphological return no matches in recipes, registry, ledger, downstream or downstream_registry. No image-based cell-profiling feature family exists at any width. The closest local material is microscopy images (bbbc*, u8/u16) and generic ML feature tables (magic_gamma, uci_*), which have low-precision columns, whereas these are 17-digit doubles from a biological imaging assay.
- Homogeneity: Single assay, single pipeline (the same CellProfiler/cytominer version across the CDRP batch), same cell line and stain set, and an identical 4,716-feature column schema on every plate. One sample = one plate. Columns mix feature kinds (areas in px, normalized intensities, texture, correlations), but that per-plate schema is fixed and recurs identically across samples, so this is one regime. Use only the CDRP batch, not other cpg projects with different pipelines. Take a bounded subset, e.g. the first 30 plates by plate id with full size (>30 MB), out of 405.
- Risks: (1) Breadth gate: a heterogeneous feature matrix might sit near existing ml_feature_table families, though the full-precision mantissas and assay structure should differ. (2) Some columns are constant or zero for every well (e.g. some granularity scales); the builder should check that no sample is dominated by one value. (3) The CSVs are aggregated per-well profiles (mean or median of per-cell values); the per-cell SQLite is too large (8 GB per plate), so per-well is the natural published record at a bounded size. (4) Download/primary ratio is about 2.4x because of text encoding, which is acceptable.
- Probe evidence: S3 ListObjectsV2 of the cpg0012 backend found 405 CDRP plate CSVs totalling 13.7 GB (1.8-34.6 MB each) alongside 7.8-8.9 GB .sqlite files. A 1-byte range GET with -L on 24277.csv returned 206. A 200 KB range read showed a 4,725-column header (Cells 1286, Cytoplasm 1274, Nuclei 1177, Image 979, Metadata 9) and full-precision double values (0.9714556719755841, 1.051879604510711, ...), with 0 empty or NaN cells in the first data row. The registry page states CC0 1.0.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_085026.jsonl`).
