# 16-bit Hunt Round 3 Download Runbook

This staged round contains ten candidate recipes. No dataset payloads were downloaded by the agent.

## Candidate State

| dataset_id | domain | primary format | download mode | expected risk |
|---|---|---|---|---|
| `nasa_aviris_classic_hyperspectral_i16` | airborne hyperspectral remote sensing | ENVI int16/uint16 cubes | AVIRIS seed page or `AVIRIS_URLS_FILE` | source page may not expose direct files |
| `tcia_nsclc_radiomics_ct_i16` | medical CT imaging | uncompressed DICOM 16-bit planes | TCIA NBIA API | selected series may use compressed transfer syntax |
| `polyhaven_hdri_exr_f16` | HDR environment imagery | OpenEXR HALF planes | Poly Haven API | local parser only accepts uncompressed HALF EXR |
| `smithsonian_openaccess_gltf_indices_u16` | 3D scan topology | GLB uint16 index accessors | Smithsonian page or `SMITHSONIAN_GLTF_URLS_FILE` | portal may not expose direct `.glb` links |
| `usgs_sidescan_sonar_tiff_u16` | marine sonar raster | uncompressed 16-bit TIFF | USGS/data.gov seed or `USGS_SIDESCAN_URLS_FILE` | many sonar mosaics are 8-bit or compressed |
| `usgs_chirp_segy_i16` | marine seismic traces | SEG-Y format-code-3 traces | USGS seed pages or `USGS_CHIRP_SEGY_URLS_FILE` | some SEG-Y files may be float/32-bit |
| `nasa_pds_sharad_radargram_i16` | planetary radargrams | PDS3 16-bit image payloads | PDS seed or `SHARAD_URLS_FILE` | exact product URLs may be needed |
| `nasa_pds_crism_trdr_i16` | planetary hyperspectral cubes | PDS3 16-bit cube/image payloads | PDS seed or `CRISM_URLS_FILE` | exact product URLs may be needed |
| `usgs_3dep_las_intensity_u16` | LiDAR point clouds | LAS uint16 intensity fields | registry seed or `USGS_3DEP_LAS_URLS_FILE` | registry likely needs exact `.las` URLs; `.laz` rejected |
| `noaa_passive_acoustic_pcm16` | underwater acoustics | WAV PCM16 frames | NOAA seed or `NOAA_PASSIVE_AUDIO_URLS_FILE` | portal may not expose direct WAV links |

## Run Commands

Run each candidate independently:

```bash
staging/<dataset_id>/download.sh
staging/<dataset_id>/build.sh
staging/<dataset_id>/verify.sh
```

All scripts write logs under `.data/logs/<dataset_id>/`. Build and verify refuse output above `1,000,000,000` primary bytes and enforce the current median/sample acceptance floor.

## Local Proxy Handling

The first run in this environment failed before downloading any payload because Python could not resolve external hostnames directly. The shared downloader now inherits `proxy=` and `noproxy=` from `~/.curlrc` when no `http_proxy` / `https_proxy` environment variables are set. If a later run fails with proxy allowlist errors, that is a network-policy failure, not a dataset-quality decision.

## Material Boundaries

Natural sample boundaries are container-native: one ENVI scene, one DICOM slice, one EXR channel plane, one glTF accessor, one TIFF image, one SEG-Y trace, one PDS product payload, one LAS tile intensity stream, or one WAV recording. The recipes do not concatenate independent files to pass the floor.
