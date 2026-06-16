# 16-bit Next Targets After Validated Promotions

This pass starts after `hf_smolllm2_135m_safetensors_f16` and
`librispeech_dev_clean_i16` were promoted. Those two were already validated
locally and should not be counted as new hunt progress.

No dataset payloads were downloaded by the agent in this pass.

## Already Accounted For

| dataset_id | state | why not count as new search progress |
|---|---|---|
| `hf_smolllm2_135m_safetensors_f16` | promoted | Already locally validated before this pass; promotion was bookkeeping. |
| `librispeech_dev_clean_i16` | promoted | Already locally validated before this pass; promotion was bookkeeping. |
| `dwd_radolan_rw_precip_i16` | staged, locally built/verified | Viable but already validated in a previous round; all samples are same-size `900x900` radar grids. |
| `nsynth_test_notes_i16` | staged, locally built/verified | Viable but already validated in a previous round; all samples are fixed-duration audio clips. |
| `polyhaven_hdri_exr_f16` | downloaded, build failed | Good HDR half-float material, but local parser cannot decode compressed OpenEXR without adding a nontrivial dependency. |

## Script Repair Started

`staging/usgs_chirp_segy_i16/download.sh` was tightened locally to include
additional USGS SEG-Y download pages discovered during this pass:

- `https://pubs.usgs.gov/ds/311/html/download.html`
- `https://pubs.usgs.gov/ds/259/html/download.html`
- `https://pubs.usgs.gov/ds/620/html/download.html`
- `https://pubs.usgs.gov/ds/526/html/download.html`
- `https://pubs.usgs.gov/ds/2007/242/html/download.html`
- `https://pubs.usgs.gov/ds/2007/254/html/download.html`
- `https://cmgds.marine.usgs.gov/catalog/whcmsc/segy/DH_SeismicProfiles_segy.html`
- `https://cmgds.marine.usgs.gov/catalog/whcmsc/segy/DH_SeismicProfiles_segy.txt`
- `https://cmgds.marine.usgs.gov/catalog/whcmsc/segy/ccb_seis_segy.html`
- `https://cmgds.marine.usgs.gov/catalog/whcmsc/segy/ccb_seis_segy.faq.html`
- `https://cmgds.marine.usgs.gov/catalog/spcmsc/2024-310-FA_seismic_metadata.faq.html`

This does not make the dataset accepted. The next required step is a user-run
download followed by local build/verify. If these pages still expose no direct
`.sgy`, `.segy`, or archive payload links in the user's environment, this
candidate remains blocked on exact URL discovery.

After the first rerun failed with `no candidate URLs discovered`, the generic
URL downloader was also repaired to scan plain-text URLs in seed documents, not
just HTML `href` attributes. This matters for FGDC-style metadata pages that
publish direct data links as text.

After the next rerun, discovery aborted on a single unreachable seed with
`Tunnel connection failed: 502 Failed to resolve host`. The generic downloader
was patched again to warn and continue when a seed page cannot be fetched. This
still does not validate the candidate; it only prevents one blocked seed from
masking usable links on later seeds.

The following rerun still produced zero candidate URLs. The CMGDS metadata
seeds were unreachable through the local proxy, and the reachable USGS
`pubs.usgs.gov` seed pages exposed no direct `.sgy`, `.segy`, or archive links.
Treat `usgs_chirp_segy_i16` as blocked until an explicit
`USGS_CHIRP_SEGY_URLS_FILE` is available.

Exact URL search then found one stronger SEG-Y lead that should be tried before
dropping the candidate entirely:

- `https://pubs.usgs.gov/ds/653/segy/`
- `https://pubs.usgs.gov/ds/653/html/download.html`

These are still not validated locally because `pubs.usgs.gov` is blocked by the
local proxy. They were added to the local download script as exact-directory and
exact-download-page seeds for the user's environment to test.

A bounded metadata scan of `https://usgs-lidar-public.s3.amazonaws.com/`
confirmed that the 3DEP public bucket is listable, but the sampled objects were
EPT `.laz` tiles rather than uncompressed `.las` tiles: 8 listing pages showed
`7,983` `.laz` objects, `17` JSON metadata files, and `0` `.las` files. Treat
`usgs_3dep_las_intensity_u16` as blocked unless exact uncompressed `.las`
objects are identified outside the sampled EPT layout.

Exact URL search also found USGS Astropedia CKAN `/do` resource-result URLs for
THEMIS controlled IR mosaics:

- Mare Acidalium daytime IR:
  `https://astrogeology.usgs.gov/ckan/dataset/e3e618dc-c8b4-4534-83ba-35fb961a8d7c/resource/eccade43-93a6-4a95-962b-2bedb58f59b1/do`
- Iapygia daytime IR:
  `https://astrogeology.usgs.gov/ckan/dataset/e79aaf47-1802-4225-9eab-dd839a773750/resource/6f5d7cde-1bbc-4c6b-ae47-4686b51729ec/do`
- Coprates daytime IR:
  `https://astrogeology.usgs.gov/ckan/dataset/e91f87c2-17d2-436e-a0c2-645863fcece7/resource/603473de-980a-40ac-946d-07c4f67c857e/do`
- Noachis nighttime IR:
  `https://astrogeology.usgs.gov/ckan/dataset/2fc320df-f33f-4d10-a319-c6aaece8ca03/resource/39357565-3b95-4cad-8fed-bf5695c85243/do`

User execution showed that these search-result `/do` URLs are stale or not real
download endpoints: the first URL returned 404. The tracked THEMIS download
script was therefore repaired again to remove those false exact URLs. It now
pins exact Astropedia product pages, extracts direct data-file links from those
pages, and only downloads links ending in supported data/container suffixes.
This is not yet an accepted dataset; it is a safer download-discovery stage that
will either produce real resource URLs in `download_plan.tsv` or fail before
downloading payloads.

The next user run found real THEMIS payload URLs and downloaded two large TIFF
mosaics, but both proved to be native 8-bit unsigned-byte rasters, not 16-bit
numeric products:

- `THEMIS_DayIR_ControlledMosaic_Arabia_000N000E_100mpp.tif`
  - source bytes: `474,486,633`
  - image shape: `17,783 x 26,674`
  - values: `474,343,742`
  - native sample type: unsigned 8-bit
- `THEMIS_DayIR_ControlledMosaic_Elysium_00N135E_100mpp.tif`
  - source bytes: `474,486,633`
  - image shape: `17,783 x 26,674`
  - values: `474,343,742`
  - native sample type: unsigned 8-bit

The PDS3 label explicitly says `SAMPLE_BITS = 8` and
`SAMPLE_TYPE = LSB_UNSIGNED_INTEGER`; the ISIS label says `Type =
UnsignedByte`. This candidate is therefore rejected for the 16-bit collection.
The download script now preflights small labels first and rejects non-16-bit
THEMIS products before downloading another multi-hundred-MB image.

The same material is still valid as native numeric 8-bit raster data. It was
salvaged into `datasets/nasa_pds_themis_ir_mosaic_u8` and locally
built/verified from the already downloaded payloads:

- dataset id: `nasa_pds_themis_ir_mosaic_u8`
- primary samples: `2`
- primary values / bytes: `948,687,484`
- natural sample boundary: one THEMIS controlled mosaic image
- sample shape: `17,783 x 26,674` for both samples
- source bytes: `474,486,633` per TIFF
- output bytes: `474,343,742` per raw pixel-plane sample
- caveat: same-size fraction is `1.0`; this should be documented as a large
  fixed-grid raster dataset, not a diverse-shape image corpus.

## Strongest Fresh Targets

These are the best next scripting targets if the goal is new 16-bit material
with different semantics. All listed targets have a public/government-open
license or terms basis; none require downloading the whole upstream corpus
before bounding the subset.

| priority | dataset_id | material | license / terms basis | natural sample | expected scale | parser path | main risk |
|---:|---|---|---|---|---|---|---|
| 1 | `nasa_pds_sharad_radargram_i16` | Mars radargram image products | NASA PDS public planetary data. | one PDS image/radargram product | likely 10s-100s MB from selected products | Python stdlib PDS3 label + raw image parser, accept only 16-bit integer products | Previous seed page exposed no direct payload links; needs exact product URLs. |
| 2 | `nasa_pds_crism_trdr_i16` | Mars hyperspectral instrument cubes | NASA PDS public planetary data. | one PDS cube/image product | bounded subset should fit under 1 GB | Python stdlib PDS3 label + raw cube parser, accept only 16-bit integer samples | Exact direct products needed; some products may use layout details the simple parser must reject. |
| 3 | `nasa_aviris_classic_hyperspectral_i16` | airborne hyperspectral ENVI cubes | NASA/JPL public science data. | one ENVI scene/cube | likely 100s MB for a small selected scene set | Python stdlib ENVI `.hdr` + raw binary parser, accept only int16/uint16 interleaves | Prior discovery found FTP links; must find stable HTTPS product URLs before retry. |
| 4 | `nasa_sdo_aia_fits_i16` | solar EUV/UV FITS images | NASA open-data policy and SDO public data access. | one FITS image | selected wavelength/time sample likely 100s MB | Python stdlib FITS parser, accept only `BITPIX = 16` images | Existing data.gov route failed; exact JSOC index found by search, but file-level FITS names still need discovery. |
| 5 | `noaa_passive_acoustic_pcm16` | underwater passive-acoustic recordings | NOAA/NCEI public data. | one WAV recording | bounded recording subset can be capped under 1 GB | Python `wave` parser, accept only PCM16 | Audio is already represented; keep only if recordings are long, natural, and materially different from speech/music clips. |
| blocked | `usgs_3dep_las_intensity_u16` | airborne LiDAR point intensity streams | USGS 3DEP public data / US government work. | one LAS tile intensity vector | likely 100s MB from selected uncompressed `.las` tiles | Python stdlib LAS header/point parser, reject `.laz`/COPC | Blocked: sampled public bucket objects are `.laz`, not `.las`; no LAZ decoder allowed. |
| blocked | `usgs_chirp_segy_i16` | marine sub-bottom seismic traces | USGS public data / US government work; prior staging already recorded this source family. | one SEG-Y trace, not whole survey concatenation | likely 100s MB from a bounded survey/file subset | Python stdlib SEG-Y reader, accept only format-code `3` signed int16 traces | Blocked: no direct payload URLs discovered from seeds; requires explicit URL list. |

## Do Not Script Yet

| candidate | reason |
|---|---|
| More Hugging Face safetensors models | Too close to `hf_smolllm2_135m_safetensors_f16`; it would be easy but low-diversity. |
| More speech/music audio corpora | Too close to LibriSpeech/FSDD/NSynth unless the signal source is materially different, such as passive acoustics. |
| More CT/DICOM medical slices | Too close to `tcia_nsclc_radiomics_ct_i16` unless the modality changes and decoding stays dependency-free. |
| More terrain DEM tiles | Too close to SKADI unless the sensor/modality changes, e.g. radargram or hyperspectral cubes rather than elevation rasters. |
| THEMIS controlled IR mosaics | Exact product pages resolve, but tested products are native 8-bit unsigned-byte rasters. Reject for the 16-bit hunt unless a different THEMIS product class with label-proven `SAMPLE_BITS = 16` is found. |
| Zenodo microscopy records found in search | Potentially useful, but Zenodo API/pages returned 403 from this environment, so license and direct file inventory could not be confirmed. Do not admit until metadata is confirmable. |
| BBBC / Cell Painting microscopy | Useful domain, but per-dataset license and exact 16-bit TIFF payload paths still need confirmation. Prior policy already excluded these until that is solved. |
| Hubble/ESA FITS Liberator pages | Likely useful astronomy FITS material, but current environment returns 403 and license/direct file inventory could not be confirmed in this pass. |
| OpenEXR HDR images | `polyhaven_hdri_exr_f16` proves the material is good but compressed EXR needs a real local decoder; do not add brittle partial decoders. |

## Proposed Next Work

Focus on exact direct URL discovery, not new parsers first:

1. Find exact PDS product URLs for SHARAD/CRISM and repair the existing PDS3
   parsers only after those URLs are confirmed.
2. Revisit `usgs_chirp_segy_i16` only if direct SEG-Y payload URLs are found
   outside the blocked seed pages.
3. Revisit `usgs_3dep_las_intensity_u16` only if uncompressed `.las` objects
   are identified; do not switch it to `.laz` without an explicit local LAZ
   decoder decision.

If exact URLs cannot be found quickly, stop and report the block instead of
adding another speculative download script.
