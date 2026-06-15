# 16-bit Hunt 2026-06-15 Error Triage

The user ran `staging/source_variety_batch_20260615_16a/download.sh` twice. One dataset downloaded and was processed successfully. Six failed or were deferred at download/source-discovery time; no failed candidate produced accepted samples.

## Current State

| dataset_id | state | local payload | action |
|---|---:|---:|---|
| `hf_smolllm2_135m_safetensors_f16` | built and verified | 269,030,016 primary bytes | keep |
| `nasa_sdo_aia_synoptic_fits_i16` | source discovery failed | 0 accepted bytes | needs alternate source |
| `nasa_pds_magellan_sar_i16` | source discovery failed | 0 accepted bytes | needs alternate source |
| `nasa_pds_messenger_mdis_basemap_i16` | source discovery failed | 0 accepted bytes | needs alternate source |
| `nasa_pds_clementine_uvvis_i16` | source discovery failed | 0 accepted bytes | needs alternate source |
| `noaa_nexrad_level2_moments_i16` | deferred | 0 accepted bytes | needs exact object keys or alternate listing |
| `nasa_pds_themis_ir_mosaic_i16` | deferred | 0 accepted bytes | needs product pages exposing direct data-file links |

## Verified Dataset: `hf_smolllm2_135m_safetensors_f16`

Source file:

| file | bytes |
|---|---:|
| `.data/downloads/hf_smolllm2_135m_safetensors_f16/model.safetensors` | 269,060,552 |

Built samples:

| metric | value |
|---|---:|
| samples | 272 |
| primary values | 134,515,008 |
| primary bytes | 269,030,016 |
| dtype distribution | 272 BF16 |
| tensor-rank distribution | 211 rank-2, 61 rank-1 |
| min sample bytes | 1,152 |
| p25 sample bytes | 221,184 |
| median sample bytes | 663,552 |
| p75 sample bytes | 1,769,472 |
| max sample bytes | 56,623,104 |
| most common size fraction | 0.330882 |

Most common sample sizes:

| bytes | samples |
|---:|---:|
| 1,769,472 | 90 |
| 1,152 | 61 |
| 221,184 | 60 |
| 663,552 | 60 |
| 56,623,104 | 1 |

Natural boundary is tensor boundary. The build copies each safetensors tensor payload byte range unchanged into a separate sample.

## Failure Details

`noaa_nexrad_level2_moments_i16` failed immediately on the default S3 prefix listing with HTTP 403. This is not a dataset-quality rejection, but it is not currently reproducible from the script without an alternate listing path or exact object keys. The script now supports `NEXRAD_KEYS_FILE=/path/to/keys.txt` for a future exact-key retry.

`nasa_sdo_aia_synoptic_fits_i16` failed because the data.gov CKAN `package_show` endpoint returned HTTP 404 for the selected package id. The fixed helper fell back to the public catalog page, but that page exposed zero direct FITS/archive links. Local page links were limited to the LMSAL homepage, DOI/citation links, a harvest record, and data.gov metadata/navigation links.

`nasa_pds_magellan_sar_i16`, `nasa_pds_messenger_mdis_basemap_i16`, and `nasa_pds_clementine_uvvis_i16` failed because the package ids used in the scripts returned HTTP 404. The scripts/manifests were updated to the alternate catalog slugs discovered during candidate research, but the rerun also returned HTTP 404 for those slugs:

| dataset_id | old suffix | new suffix |
|---|---|---|
| `nasa_pds_magellan_sar_i16` | `260f8` | `c7816` |
| `nasa_pds_messenger_mdis_basemap_i16` | `883d5` | `d5a6e` |
| `nasa_pds_clementine_uvvis_i16` | `9f307` | `1beff` |

`nasa_pds_themis_ir_mosaic_i16` failed because the selected direct USGS resource URL returned HTTP 404. The script no longer treats product pages as payloads; it fetches selected product pages, extracts direct data-file links, and fails if none are found.

## Rerun Commands

The main batch now skips all unresolved candidates by default and only revalidates/reuses the HF checkpoint:

```bash
staging/source_variety_batch_20260615_16a/download.sh
```

To explicitly retry the deferred sources:

```bash
INCLUDE_DEFERRED=1 staging/source_variety_batch_20260615_16a/download.sh
NEXRAD_KEYS_FILE=/path/to/nexrad_keys.txt staging/noaa_nexrad_level2_moments_i16/download.sh
staging/nasa_pds_themis_ir_mosaic_i16/download.sh
```

The SDO/PDS candidates should not be rerun without alternate source URLs; the current catalog paths have failed with no acceptable direct payload links.
