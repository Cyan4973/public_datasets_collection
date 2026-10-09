# Cell Painting CDRP CellProfiler per-well profiles, float64

This recipe collects image-based morphological profiles from the CDRP
bioactive-compound Cell Painting screen (Gallery project
`cpg0012-wawer-bioactivecompoundprofiling`, Bray et al. 2017, GigaScience).
U2OS cells were treated with compounds in 384-well plates, stained with five
dyes (DNA, ER, RNA, AGP, Mito) and imaged at 6 sites per well. CellProfiler
measured every cell, and the Broad profiling pipeline aggregated the
measurements per well into `backend/CDRP/<plate>/<plate>.csv`. The current
files are the 2023 re-profiling of the original images.

One sample is one plate: a row-major float64 matrix of wells (source order
a01..p24, usually 384 rows) by 4,600 feature columns (Cells, Cytoplasm,
Nuclei and Image features: shape, intensity, texture, granularity, radial
distribution, correlation, neighbour distances, image quality, thresholds).
The source cells are decimal renderings of doubles with up to 17 significant
digits, so `float()` recovers the exact value and nothing is rounded.

## Scope

- 50 plates: the first 50 CDRP plate ids (24277..24588) among the 387 complete
  33-35 MB CSVs, out of 405 CDRP plate CSVs in total. Plate ids, sizes and S3
  ETags are pinned in `plates.tsv`; `discover.sh` regenerates that list from
  an anonymous ListObjectsV2 call and diffs it.
- Download: 1,723,183,926 bytes of CSV. Realized primary output: 50 samples,
  19,190 wells x 4,600 columns = 88,274,000 float64 values = 706,192,000
  bytes (aggregate SHA-256 9fc2d7f8...b47d). Three source plates (24305,
  24307, 24352) have 383 rows; 7 wells on 5 plates were dropped by the
  missing-value rule (below).
- The per-plate `.sqlite` files (7.8-8.9 GB each, per-cell data) and the
  other Gallery projects (different pipelines) are not used.

## Column policy

The 4,725-column header must match a pinned SHA-256 on every plate, so the
column order is fixed and identical across plates. The fixed name patterns
below exclude 125 columns. They are listed in `scripts/cdrp.py` and in the
manifest:

| pattern | count | why |
|---|---|---|
| `^Metadata_` | 9 | plate/well ids, site and object counts |
| `_Number_Object_Number$` | 2 | object-number bookkeeping |
| `_Parent_` | 1 | parent object id |
| `_Children_.*_Count$` | 2 | child counts (constant 1) |
| `_Neighbors_(First\|Second)ClosestObjectNumber_` | 6 | object ids |
| `_Location_` | 95 | pixel centroids near the field centre, Z always 0 |
| `^Image_ImageQuality_Scaling_` | 5 | constant bit-depth scaling |
| `^Image_ImageQuality_TotalArea_` | 5 | constant field pixel area |

The remaining 4,600 columns are always kept, including columns that are
structurally zero on some wells (for example the inner cytoplasm
radial-distribution bins of the mito tubeness image). Columns are never
dropped per plate.

## Missing values

A well row with an empty, unparsable, NaN or infinite value in any kept
column is dropped whole and listed under `dropped_wells` in the index. A
plate that loses more than 10% of its rows, or ends up with fewer than 300
wells, fails the build. NaN is never emitted.

Realized: 7 wells dropped out of 19,197 (24279 e19, 24306 p13, 24310 c06,
24320 o20/p22, 24357 l04/o20). Spot checks show near-empty wells (2-3
segmented cells) with empty neighbour-distance/angle cells (undefined with
fewer than 3 neighbours), and one well with a single empty
`Cells_AreaShape_FormFactor`.

## Run

```bash
bash staging/cellpainting_cdrp_cellprofiler_well_profiles_f64/download.sh
bash staging/cellpainting_cdrp_cellprofiler_well_profiles_f64/build.sh
bash staging/cellpainting_cdrp_cellprofiler_well_profiles_f64/verify.sh
```

`download.sh` checks the CC0 line in the AWS Open Data Registry entry. For
each plate it compares the live ETag and size with `plates.tsv` and then
downloads with resumable curl (`-C -`, stall-based abort). It then checks the
pinned header hash, the field count on every row, that Metadata_Plate equals
the plate id, that wells are unique, and that the plate has 300-384 rows.
`verify.sh` re-parses every CSV with an independent `str.split` parser and
requires byte-identical samples. Logs go to
`.data/logs/cellpainting_cdrp_cellprofiler_well_profiles_f64/`.

## License

CC0 1.0 (AWS Open Data Registry entry for the Cell Painting Gallery). Please
cite Bray et al. 2017 (doi:10.1093/gigascience/giw014) and the Cell Painting
Gallery.
