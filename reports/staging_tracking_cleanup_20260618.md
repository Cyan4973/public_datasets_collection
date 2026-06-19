# Staging Tracking Cleanup 2026-06-18

## Problem

`staging/README.md` and `.gitignore` define `staging/` as an ignored draft area.
Only `staging/README.md` should be tracked. Despite that rule, 60 staged recipe
files across 15 `staging/<dataset_id>/` directories had been committed.

## Index Cleanup

The following tracked staging directories were removed from the git index with
`git rm --cached`; local ignored working-tree copies were preserved.

| staging directory | tracked files | promoted dataset recipe present |
|---|---:|---|
| `staging/dwd_radolan_rw_precip_i16` | 5 | no |
| `staging/geofabrik_liechtenstein_osm_pbf_u8` | 5 | no |
| `staging/google_fonts_ofl_ttf_u8` | 5 | no |
| `staging/hf_smolllm2_135m_safetensors_f16` | 5 | yes |
| `staging/librispeech_dev_clean_i16` | 5 | yes |
| `staging/nasa_pds_clementine_uvvis_i16` | 3 | no |
| `staging/nasa_pds_magellan_sar_i16` | 3 | no |
| `staging/nasa_pds_messenger_mdis_basemap_i16` | 3 | no |
| `staging/nasa_pds_themis_ir_mosaic_i16` | 3 | no |
| `staging/nasa_sdo_aia_synoptic_fits_i16` | 3 | no |
| `staging/natural_earth_vector_shp_u8` | 5 | no |
| `staging/ncbi_refseq_viral_genomes_u8` | 5 | no |
| `staging/noaa_nexrad_level2_moments_i16` | 3 | no |
| `staging/nsynth_test_notes_i16` | 5 | no |
| `staging/source_variety_batch_20260615_16a` | 2 | no |

After cleanup, `git ls-files staging` reports only:

```text
staging/README.md
```

## Dependency Audit

Tracked accepted dataset recipes were checked for hard-coded references to the
removed staging paths. No accepted recipe under `datasets/` references any of
the removed `staging/<dataset_id>/` directories.

The two removed staging directories that also have promoted recipes were
validated from local `.data` cache after the cleanup:

| dataset | download | build | verify |
|---|---|---|---|
| `hf_smolllm2_135m_safetensors_f16` | pass, existing local files | pass | pass |
| `librispeech_dev_clean_i16` | pass, existing local archive | pass | pass |

The Macrostrat recipes touched during the same cleanup were also revalidated
from local `.data` cache:

| dataset | download | build | verify |
|---|---|---|---|
| `macrostrat_columns` | pass, cache hit | pass | pass |
| `macrostrat_sections` | pass, cache hit | pass | pass |

Historical reports still mention staged runbook paths from the corresponding
hunt sessions. Those reports are historical records, not accepted recipe
dependencies.
