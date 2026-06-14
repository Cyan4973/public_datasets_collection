# 8-bit Hunt Runbook 2026-06-13

This batch deliberately targets naturally large, variable-size 8-bit samples.
None of these recipes should pass by concatenating small records.

Hard bounds for this hunt:

- accepted primary output must be at most `1,000,000,000` bytes
- candidates are not victories until the user-run `download.sh`, local `build.sh`, and local `verify.sh` have completed
- reports must include sample count, total size, min/p10/p25/median/p75/p90/max sample sizes, and same-size concentration before promotion

## Staged Recipes

| dataset_id | domain | natural sample | current state | risk |
|---|---|---|---|---|
| `ncbi_refseq_viral_genomes_u8` | viral reference genomics | one viral FASTA record | unvalidated; must be measured after user download/build | not diverse if paired with other FASTA datasets; median size and total size unknown |
| `geofabrik_liechtenstein_osm_pbf_u8` | geospatial map data | one decompressed OSM PBF PrimitiveBlock | unvalidated; must be measured after user download/build | Geofabrik `latest` changes over time; size distribution unknown |

## Rejected Before Download

| dataset_id | reason |
|---|---|
| `ucsc_hg38_chromosomes_u8` | expected primary output is about `3.09 GB` for 25 hg38 primary chromosomes, above the `1 GB` cap |

## User-run Commands

```sh
bash staging/ncbi_refseq_viral_genomes_u8/download.sh
bash staging/geofabrik_liechtenstein_osm_pbf_u8/download.sh
```

After downloads complete:

```sh
bash staging/ncbi_refseq_viral_genomes_u8/build.sh && bash staging/ncbi_refseq_viral_genomes_u8/verify.sh
bash staging/geofabrik_liechtenstein_osm_pbf_u8/build.sh && bash staging/geofabrik_liechtenstein_osm_pbf_u8/verify.sh
```

Detailed state report after successful builds:

```sh
python3 tools/report_dataset_state.py \
  staging/ncbi_refseq_viral_genomes_u8 \
  staging/geofabrik_liechtenstein_osm_pbf_u8 \
  --output-md reports/8bit_hunt_20260613_dataset_state.md \
  --output-tsv reports/8bit_hunt_20260613_dataset_state.tsv
```

## Acceptance Notes

- `ncbi_refseq_viral_genomes_u8` should be rejected if the realized median viral record is below `1,000` bytes.
- `geofabrik_liechtenstein_osm_pbf_u8` should be rejected if the realized PBF PrimitiveBlocks are all identical size or if the extract is too small.
- Neither remaining candidate should be promoted or committed as accepted until the measured report exists and passes review.
