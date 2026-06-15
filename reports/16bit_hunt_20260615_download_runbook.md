# 16-bit Hunt 2026-06-15 Download Runbook

This is the download-script wave for the new 16-bit hunt. The agent did not download dataset payloads.

## Included Scripts

| dataset_id | domain | access path | default bound | expected novelty | risk |
|---|---|---|---|---|---|
| `hf_smolllm2_135m_safetensors_f16` | model checkpoint tensors | direct Hugging Face file URLs | one checkpoint under 1 GB | genuinely new tensor-weight material | reject if checkpoint dtype is not F16/BF16 |
| `noaa_nexrad_level2_moments_i16` | weather radar volumes | public NOAA S3-compatible bucket listing | 8 volume files, 200 MB/file cap | different radar encoding from DWD RADOLAN | parser complexity after download |
| `nasa_sdo_aia_synoptic_fits_i16` | solar FITS imagery | data.gov package resource discovery | 8 resources, 500 MB/file cap | solar telescope imagery | catalog may not expose direct FITS files |
| `nasa_pds_themis_ir_mosaic_i16` | Mars thermal IR mosaics | selected USGS/Astropedia URLs | 3 resources, 750 MB/file cap | planetary thermal imagery | selected URLs may be landing pages or archives |
| `nasa_pds_magellan_sar_i16` | Venus SAR imagery | data.gov/PDS package discovery | 6 resources, 750 MB/file cap | planetary radar imagery | catalog may expose only landing metadata |
| `nasa_pds_messenger_mdis_basemap_i16` | Mercury camera basemaps | data.gov/PDS package discovery | 6 resources, 750 MB/file cap | planetary camera imagery | catalog may expose only landing metadata |
| `nasa_pds_clementine_uvvis_i16` | lunar multispectral imagery | data.gov/PDS package discovery | 6 resources, 750 MB/file cap | lunar multispectral imagery | catalog may expose only landing metadata |

## Commands

Run the surviving active candidate:

```bash
staging/source_variety_batch_20260615_16a/download.sh
```

The batch skips all unresolved source-discovery failures by default after rerun validation. To include them anyway:

```bash
INCLUDE_DEFERRED=1 staging/source_variety_batch_20260615_16a/download.sh
```

Or run individually:

```bash
staging/hf_smolllm2_135m_safetensors_f16/download.sh
staging/hf_smolllm2_135m_safetensors_f16/build.sh
staging/hf_smolllm2_135m_safetensors_f16/verify.sh
staging/noaa_nexrad_level2_moments_i16/download.sh
staging/nasa_sdo_aia_synoptic_fits_i16/download.sh
staging/nasa_pds_themis_ir_mosaic_i16/download.sh
staging/nasa_pds_magellan_sar_i16/download.sh
staging/nasa_pds_messenger_mdis_basemap_i16/download.sh
staging/nasa_pds_clementine_uvvis_i16/download.sh
```

Useful bounds:

```bash
FILE_LIMIT=4 staging/noaa_nexrad_level2_moments_i16/download.sh
NEXRAD_KEYS_FILE=/path/to/nexrad_keys.txt staging/noaa_nexrad_level2_moments_i16/download.sh
FILE_LIMIT=2 staging/nasa_pds_themis_ir_mosaic_i16/download.sh
MAX_FILE_BYTES=300000000 staging/nasa_sdo_aia_synoptic_fits_i16/download.sh
```

## State After First User Run

`hf_smolllm2_135m_safetensors_f16` downloaded, built, and verified locally:

| metric | value |
|---|---:|
| source checkpoint bytes | 269,060,552 |
| samples | 272 |
| primary bytes | 269,030,016 |
| primary values | 134,515,008 |
| dtype | BF16 only |
| sample size range | 1,152 to 56,623,104 bytes |
| median sample size | 663,552 bytes |
| most common size fraction | 0.330882 |

Failure triage is recorded in `reports/16bit_hunt_20260615_error_triage.md`. The catalog helper was tightened so data.gov page fallback only accepts direct data-file URLs and cannot silently accept HTML landing pages as samples.

The rerun confirmed that the SDO/data.gov and three PDS/data.gov candidates still do not expose usable direct payload links through the current catalog paths. They should remain deferred until alternate direct source URLs are identified.

## Deliberately Not Scripted Yet

- `usgs_3dep_las_intensity_u16`: qualitatively strong, but needs exact LAS object keys or a reproducible public listing path. Avoiding LAZ/COPC because that would require LASzip/COPC tooling.
- `nasa_aviris_ng_envi_i16`: qualitatively strong, but likely Earthdata-authenticated and may be float32 or HDF/NetCDF depending product. Needs exact ENVI raw product URLs before scripting.
- `nasa_pds_mola_megdr_i16`: backup only because it is too close to existing Skadi/SRTM elevation geometry.
- `soho_lasco_fits_i16`: backup only because it overlaps the SDO solar FITS family.

## Expected Next Step

After the user runs these scripts, inspect `.data/logs/<dataset_id>/download.latest.log` and `.data/downloads/<dataset_id>/download_inventory.json`, then decide which candidates deserve build/verify scripts.
