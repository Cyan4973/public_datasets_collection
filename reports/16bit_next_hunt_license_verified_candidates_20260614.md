# 16-bit Next Hunt: License-First Candidate Slate

This is a review slate only. No download scripts have been written and no dataset payloads have been fetched by the agent.
Some entries were later deferred or superseded; consult
`attempts/dataset_status.tsv` before treating this historical slate as current.

Selection rules used here:

- license or public-data terms must be identifiable before candidate admission;
- avoid repeating existing ECG/EEG/PhysioNet waveform, speech, terrain, station-weather, or table-derived `uint16` shapes unless the material is clearly different;
- prefer native 16-bit source material or lossless source material decoded to native 16-bit values;
- require a portable build path using Python standard library plus already-available local tools such as `ffmpeg`;
- reject candidates that require GDAL/PIL/DICOM/HDF5/special GIS tooling unless a local `feature` provider is available.

## First-Wave Candidates

| priority | dataset_id | material | license / terms status | natural sample | expected scale | build path | risk |
|---:|---|---|---|---|---|---|---|
| 1 | `dwd_radolan_rw_precip_i16` | German weather-radar precipitation composites | DWD Open Data area; DWD data distributed under German open-data attribution terms / GeoNutzV-style terms. Source: `https://www.dwd.de/EN/ourservices/cdc/cdc.html` | one RADOLAN RW composite file | choose a bounded hourly or daily window, likely hundreds of 900x900 int16 grids and <1 GB raw | Python stdlib binary parser | Radar/weather domain, but raster composites differ materially from existing station weather tables. |
| 2 | `noaa_nexrad_level2_moment_i16` | NEXRAD radar radial moment data | NOAA/NCEI public data; AWS Open Data registry. Sources: `https://registry.opendata.aws/noaa-nexrad/`, `https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncdc:C00345/html` | one radar volume or moment sweep | bounded station/day subset, expected hundreds of MB | Python stdlib parser for selected uncompressed/bzip2 blocks | Parser is more complex than RADOLAN; keep only if implementation remains transparent. |
| 3 | `sdss_corrected_frame_fits_i16` | astronomical CCD corrected imaging frames | SDSS public data release with publication/citation policy. Source: `https://www.sdss.org/collaboration/publication-policy/` | one FITS frame | dozens of frames, likely 100-500 MB | Python stdlib FITS parser, only admit `BITPIX=16` images | Deferred; see `attempts/dataset_status.tsv` and `attempts/20260614_deferred_sdss_corrected_frame_fits_i16.md`. |
| 4 | `sdo_aia_fits_i16` | solar EUV/UV FITS images | NASA open science/data policy; SDO public data access. Sources: `https://sdo.gsfc.nasa.gov/data/dataaccess.php`, `https://earthdata.nasa.gov/nasa-data-policy` | one AIA FITS image | bounded wavelength/time sample, likely 100s MB | Python stdlib FITS parser, only admit `BITPIX=16` images | Avoid too many astronomy FITS recipes in one batch. |
| 5 | `nasa_pds_mola_megdr_i16` | Mars MOLA gridded elevation rasters | NASA PDS public planetary data; PDS Geosciences MGS/MOLA catalog. Source: `https://pds-geosciences.wustl.edu/missions/mgs/mola.html` | one PDS IMG tile | selected global/regional tiles, likely 100s MB | Python stdlib PDS label + raw IMG parser | Topography overlaps Skadi in data geometry, but planetary source and instrument differ. |
| 6 | `nasa_pds_themis_ir_mosaic_i16` | Mars THEMIS thermal-infrared controlled mosaics | NASA/PDS/USGS public planetary data. Source: `https://astrogeology.usgs.gov/search/map/mars-themis-controlled-mosaics-and-final-smithed-kernels` | one PDS/IMG or raw mosaic tile | selected regional mosaics, likely 100s MB | Python stdlib PDS label + raw IMG parser | Confirm product is integer 16-bit before scripting. |
| 7 | `nsynth_test_notes_i16` | musical instrument note waveforms | NSynth is published by Magenta/Google; license stated as Creative Commons Attribution 4.0 in dataset documentation. Source: `https://magenta.withgoogle.com/datasets/nsynth` | one WAV note | test split only, about 4k fixed-duration samples, likely 500-600 MB raw PCM16 | Python `wave` if WAV, or `ffmpeg` fallback | Audio domain is represented by speech, but musical instruments are different; fixed sample size is the main weakness. |

## Lower-Priority Backups

These have acceptable license/public-data posture, but should not all be scripted in the same batch because they repeat a material family already present in the first-wave set.

| dataset_id | material | license / terms status | why not first-wave |
|---|---|---|---|
| `nasa_pds_messenger_mdis_basemap_i16` | Mercury MDIS map-projected basemap imagery | NASA/PDS MESSENGER public data release. Source: `https://catalog.data.gov/dataset/mess-mdis-map-proj-low-incidence-angle-basemap-rdr-v1-0-883d5` | Planetary raster imagery overlaps THEMIS; good backup if THEMIS product is not clean 16-bit. |
| `nasa_pds_lroc_wac_mosaic_i16` | Lunar LROC WAC mosaic imagery | NASA/LRO public data via PDS/USGS/Astropedia. Source: `https://astrogeology.usgs.gov/search/map/moon_lro_lroc_wac_global_morphology_mosaic_100m` | Another planetary raster; avoid overloading the batch with similar mosaics. |
| `noaa_etopo_global_relief_i16` | global bathymetry/topography grid | NOAA/NCEI ETOPO public data. Source: `https://www.ncei.noaa.gov/products/etopo-global-relief-model` | Too close to Skadi and likely single-sample; keep only as a clean fallback. |
| `noaa_nexrad_level3_product_i16` | NEXRAD Level-III radar products | NOAA public data. Source: `https://catalog.data.gov/dataset/noaa-next-generation-radar-nexrad-level-3-products2` | Similar to Level-II/RADOLAN; use only if Level-II parser is too complex. |

## Explicitly Excluded For Now

| source | reason |
|---|---|
| Additional PhysioNet ECG/EEG/sleep datasets | Too similar to existing ECG/EEG waveform recipes and the recent LibriSpeech waveform addition. |
| CMU Arctic speech | License/use terms are not sufficiently clear for this pass and speech is already represented. |
| TinySOL orchestral notes | Likely useful, but license confirmation was not strong enough in this pass; do not script until the exact Zenodo record license is verified. |
| ESC-50 / UrbanSound-like environmental audio | Commonly non-commercial or per-clip license risk; exclude unless a specific permissive subset is documented. |
| BBBC microscopy image sets | Useful domain, but license is per-image-set and was not confirmed strongly enough in this pass; do not script until a specific set has explicit acceptable terms. |
| Cell Tracking Challenge microscopy | License and redistribution terms were not confirmed strongly enough in this pass. |
| Landsat / GeoTIFF-heavy sources | Source data are public, but GDAL/PIL-style dependency was rejected; include only if a simple portable parser is proven for the exact selected files. |

## Proposed Autonomous Next Step

If approved, script the first wave in this order:

1. `dwd_radolan_rw_precip_i16`
2. `sdss_corrected_frame_fits_i16` only after replacing the failed directory-discovery strategy with exact stable direct frame URLs
3. `nasa_pds_mola_megdr_i16`
4. `nasa_pds_themis_ir_mosaic_i16`
5. `nsynth_test_notes_i16`
6. `sdo_aia_fits_i16`

Keep `noaa_nexrad_level2_moment_i16` as a stretch target because parser complexity is higher.
