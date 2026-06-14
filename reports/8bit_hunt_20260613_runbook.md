# 8-bit Hunt Runbook 2026-06-13

This batch deliberately targets naturally large, variable-size 8-bit samples.
None of these recipes should pass by concatenating small records.

## Staged Recipes

| dataset_id | domain | natural sample | expected size behavior | risk |
|---|---|---|---|---|
| `ucsc_hg38_chromosomes_u8` | human reference genomics | one primary chromosome FASTA record | 25 variable-size samples, mostly very large | large download and output |
| `ncbi_refseq_viral_genomes_u8` | viral reference genomics | one viral FASTA record | many variable-size genome/segment samples | median size must be confirmed after download |
| `geofabrik_liechtenstein_osm_pbf_u8` | geospatial map data | one decompressed OSM PBF PrimitiveBlock | variable-size binary protobuf blocks | Geofabrik `latest` changes over time |

## User-run Commands

```sh
bash staging/ucsc_hg38_chromosomes_u8/download.sh
bash staging/ncbi_refseq_viral_genomes_u8/download.sh
bash staging/geofabrik_liechtenstein_osm_pbf_u8/download.sh
```

After downloads complete:

```sh
bash staging/ucsc_hg38_chromosomes_u8/build.sh && bash staging/ucsc_hg38_chromosomes_u8/verify.sh
bash staging/ncbi_refseq_viral_genomes_u8/build.sh && bash staging/ncbi_refseq_viral_genomes_u8/verify.sh
bash staging/geofabrik_liechtenstein_osm_pbf_u8/build.sh && bash staging/geofabrik_liechtenstein_osm_pbf_u8/verify.sh
```

Detailed state report after successful builds:

```sh
python3 tools/report_dataset_state.py \
  staging/ucsc_hg38_chromosomes_u8 \
  staging/ncbi_refseq_viral_genomes_u8 \
  staging/geofabrik_liechtenstein_osm_pbf_u8 \
  --output-md reports/8bit_hunt_20260613_dataset_state.md \
  --output-tsv reports/8bit_hunt_20260613_dataset_state.tsv
```

## Acceptance Notes

- `ucsc_hg38_chromosomes_u8` is intentionally few-sample but high-volume; the samples are natural chromosomes and have highly variable sizes.
- `ncbi_refseq_viral_genomes_u8` should be rejected if the realized median viral record is below `1,000` bytes.
- `geofabrik_liechtenstein_osm_pbf_u8` should be rejected if the realized PBF PrimitiveBlocks are all identical size or if the extract is too small.
