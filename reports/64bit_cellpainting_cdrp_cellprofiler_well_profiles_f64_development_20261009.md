# Cell Painting CDRP CellProfiler per-well profiles float64 development

## Outcome

Accepted `cellpainting_cdrp_cellprofiler_well_profiles_f64`: image-based morphological profiles from the CDRP bioactive-compound Cell Painting screen. The source is Cell Painting Gallery project `cpg0012-wawer-bioactivecompoundprofiling` (Bray et al. 2017; Wawer et al. 2014).

This is the corpus's first family of image-derived cell-profiling features. The bbbc* microscopy recipes keep raw image intensities. This recipe keeps the per-well CellProfiler measurement profiles the Broad pipeline publishes as its operational artifact. Multi-feature measurement tables already exist locally (`ml_feature_table`: magic_gamma, uci_superconductivity, uci_steel_plates). The novelty is therefore recorded as a new source and quantity (`new_source`), not a new modality. Measured breadth is OK: the nearest family is `hutubs_measured_hrir_f64` at feature distance 0.0842 (loss 0.0167).

## Source and rights

- Source: anonymous public S3 bucket `cellpainting-gallery`, objects `cpg0012-wawer-bioactivecompoundprofiling/broad/workspace/backend/CDRP/<plate>/<plate>.csv`. These are the 2023 re-profiling, LastModified 2023-02-04/05.
- Population: 405 CDRP plate CSVs, 13,715,790,396 bytes; 395 of them are larger than 30 MB. The 7.8-8.9 GB per-plate per-cell `.sqlite` files are never fetched.
- Selection: the first 50 plate ids among CSVs larger than 30 MB (24277..24588). No smaller CSV falls in that id range.
- Pinning: `plates.tsv` records each plate's id, size, multipart S3 ETag, LastModified and key, and `download.sh` re-checks the live ETag and size before downloading.
- Downloaded: 1,723,183,926 bytes of CSV.
- License: CC0 1.0. The AWS Open Data Registry entry `cellpainting-gallery.yaml` states "License: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication, but please do cite the corresponding publication for each dataset". Its bucket resource description lists "extracted features (CSV)". `download.sh` fetches the entry and requires both the CC0 line and the bucket ARN.
- Safety: compound-treated U2OS cultured cell line; no personal data.

## Shape and conversion

Each natural record is one 384-well assay plate's aggregated profile table. A sample is the row-major `well x 4,600 feature` matrix in source row order (a01..p24) and source column order, stored as little-endian float64.

- Every plate must carry the identical pinned 4,725-column header (SHA-256 `4d3886b4…e343`).
- Fixed name patterns exclude 125 columns:
  - `^Metadata_` (plate/well ids, object counts)
  - object-number, parent and children bookkeeping
  - closest-neighbour object IDs
  - `_Location_` centroids
  - constant `Image_ImageQuality_Scaling_` and `_TotalArea_`
- The kept 4,600-column list is hash-pinned (`0f6b7a99…4eb4`).
- Kept features cover Cells/Cytoplasm/Nuclei AreaShape, Intensity, Texture, Granularity, RadialDistribution, Correlation, Neighbors distances, angles and counts, and ObjectSkeleton, plus Image Granularity, Texture, ImageQuality and Threshold.
- Each cell is parsed with `float()`, which recovers the source double exactly.
- The per-well aggregation is a mean: integer per-cell features such as Area appear as fractions like 3603.3634311512415 = sum/443.

Missing values: a well with any empty, NaN or infinite kept cell is dropped whole. A plate fails if it loses more than 10% of its wells or keeps fewer than 300. Seven of 19,197 source wells were dropped:

- 24279 e19, 24306 p13, 24310 c06, 24320 o20/p22, 24357 l04/o20
- In the cases checked these are 1-2-cell wells with undefined neighbour statistics, plus one 604-cell well (24357 l04) with an empty `Cells_AreaShape_FormFactor`.
- Three source plates (24305, 24307, 24352) natively have 383 rows.

## Accepted output

- Primary samples: 50, one per plate
- Wells emitted: 19,190 of 19,197 source rows
- Columns per well: 4,600
- Primary values: 88,274,000
- Primary bytes: 706,192,000
- Sample size: 1,757,200-1,766,400 values (14,057,600-14,131,200 bytes); median 1,766,400 values
- Global value range: -48.896 to 89,949.29
- Maximum per-sample mode fraction: 0.0143 (value 0.0)
- Columns constant across the whole output: 8 of 4,600
- Aggregate SHA-256: `9fc2d7f8371283f5f756200ac9a4bbf511b880b146d6935127391470e3b1b47d`

## Judge checks

- `python3 tools/autocollect/gate.py staging/cellpainting_cdrp_cellprofiler_well_profiles_f64`: PASS with no warnings.
- `bash staging/.../verify.sh`, run by the judge:
  - exit 0, byte-identical re-derivation of all 50 samples with an independent `str.split` parser
  - aggregate SHA-256 above reproduced; 8/4600 constant columns
- `build.sh` reads only local `.data/downloads/<id>/plates/*.csv`, and `scripts/cdrp.py` is stdlib only with no network.
- Live anonymous S3 ListObjectsV2 probe: 405 CSVs, not truncated. The first 50 with size >30 MB match `plates.tsv` exactly on plate, size, ETag, LastModified and key.
- Bytes, decoded with `struct` for plates 24277, 24357 and 24588:
  - 98.3-98.4% of values are not float32-exact, and the exact ones are only 0.0 and 1.0, so the width is genuine float64.
  - 97.8% of values are distinct; binary exponents span -26..14.
  - Column ranges are physically plausible: Cells area 1.1k-9.6k px², DNA mean intensity 0.002-0.009, neighbour counts 0-5.4, EulerNumber 0.948-1.0.
  - 50 distinct sample SHA-256s.
- 6,000 random (well, feature) cells across three plates matched `float(csv_text)` bit-exactly. The raw CSV rows of the dropped wells show the empty cells described above.
- Kept-column audit: no ExecutionTime, ImageNumber, URL, file or group proxy columns remain.
- Rights: the judge read the downloaded registry YAML; CC0 1.0 covers the bucket including the extracted-feature CSVs. No credentials appear in any script.
- Novelty:
  - `novelty.py --url` (plate URL, registry page, bucket name) and `--terms` (cellpainting, cell painting, cellprofiler, cytominer, pycytominer, morpholog, cpg0012, CDRP) matched only this candidate.
  - `--type cell_morphology_profile --instrument broad_cellpainting_cellprofiler_cytominer --archive aws_cellpainting_gallery` returned 0/0/0.
- Homogeneity: one assay, one cell line and stain set, and one 2023 re-profiling run, with an identical pinned schema on every plate. Per-column units differ but sit at fixed positions and recur identically in every sample. Accepted event x channel record matrices (`zenodo_metaclean_fcs_u32`, `figshare_fukuchi_forceplate_c3d_f32`) are the precedent.
- Minor documentation imprecisions, not material to acceptance:
  - The README says 387 complete 33-35 MB CSVs; the live listing has 395 CSVs above 30 MB.
  - The builder summary describes the dropped near-empty wells as having 2-3 cells; the checked ones have 1-2.
