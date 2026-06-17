# Non-64-bit Varied Numeric Source Hunt - 2026-06-17

Scope: look for varied numeric-series sources where the primary representation is
not 64-bit. No dataset payloads were downloaded for this report.

## Existing Coverage To Avoid Repeating

The accepted collection is already heavy in:

- 64-bit API/table/time-series material: finance, SEC, World Bank/FRED/OWID,
  NASA POWER, USGS NWIS, package registries, metadata catalogs.
- Station weather and climate tables.
- Several 16-bit medical/audio/tensor/raster families: LibriSpeech/FSDD,
  PhysioNet ECG/EEG, TCIA CT slices, Sentinel-2 reflectance, SRTM/Skadi,
  Smithsonian mesh indices, SmolLM2 tensors.
- Many small derived API metadata counters and identifiers.

Good next candidates should therefore add new material shapes: radar composites,
passive-acoustic recordings, instrument/science rasters, point-cloud attributes,
seismic/radar traces, and motion/trajectory streams.

## Variety Assessment

This table is stricter than source-level novelty. A candidate is `strong` only
if its material generation process and sample geometry differ from accepted
datasets, not just because it comes from a new portal.

| dataset_id | variety verdict | closest accepted datasets | decision |
|---|---|---|---|
| `dwd_radolan_rw_precip_i16` | medium-high | `sentinel2_l2a_reflectance_cogs_u16`, `nasa_pds_themis_ir_mosaic_u8`, `tcia_nsclc_radiomics_ct_i16`, NOAA station/radar-adjacent weather families | Keep. It is still raster/weather-adjacent, but the material is operational radar precipitation composites, not optical imagery, CT, terrain, or station scalar time series. |
| `nsynth_test_notes_i16` | medium-low | `librispeech_dev_clean_i16`, `fsdd_spoken_digits`, PhysioNet waveform families | Deprioritize. Musical instrument notes are semantically different from speech, but the trainer still sees fixed-length PCM16 audio waveforms. Keep only if we explicitly want more audio diversity. |
| `noaa_passive_acoustic_pcm16` | medium | `librispeech_dev_clean_i16`, `fsdd_spoken_digits`, `nsynth_test_notes_i16` if accepted | Conditional. Long environmental underwater recordings are more different than musical notes, but still audio waveform material. Useful only if recordings are long and natural, not short clips. |
| `gwosc_event_strain_f32` | high | `seismic_waveform_i32`, PhysioNet waveforms | Keep if exact simple payloads exist. Detector strain is a scientific instrument waveform with different units, noise, sampling, and event structure from audio/ECG/seismic counts. |
| `noaa_nexrad_level2_moments_i16_or_u8` | high | `dwd_radolan_rw_precip_i16` if accepted, NOAA weather tables | Keep as a later source if parser is clean. Polar/radial radar volumes are materially different from gridded RADOLAN composites and scalar weather tables. |
| `sdss_corrected_frame_fits_i16` | medium | Sentinel/THEMIS/CT/WorldClim rasters | Conditional. Astronomy CCD frames are a new instrument domain, but still 2D image rasters; useful if exact URLs are found and sample sizes vary. |
| `nasa_sdo_aia_synoptic_fits_i16` | medium | Sentinel/THEMIS/CT/WorldClim rasters, SDSS if accepted | Conditional. Solar FITS imagery is new science material, but another 2D raster. Avoid accepting both SDSS and SDO in the same hunt unless we need raster coverage. |
| `nasa_pds_sharad_radargram_i16` | high | `seismic_waveform_i32`, raster families | Keep if exact URLs exist. Radargrams are instrument cross-section/radar traces, not ordinary image rasters or scalar waveforms. |
| `usgs_chirp_segy_i16` | high | `seismic_waveform_i32` | Keep if exact URLs exist. Marine sub-bottom SEG-Y traces are close to seismic waveform only at a broad level; trace/file layout and domain are different enough. |
| `usgs_3dep_las_intensity_u16` | high | `smithsonian_openaccess_gltf_indices_u16`, geospatial rasters | Keep only with uncompressed LAS. Point-cloud intensity vectors are a new geometry and source process. |

## Best Immediate Candidates

| priority | dataset_id | width | material / shape | source and license status | current state | recommendation |
|---:|---|---:|---|---|---|---|
| 1 | `dwd_radolan_rw_precip_i16` | 16 | German weather-radar precipitation composite rasters, one 900x900 grid per RADOLAN RW file. | DWD Open Data / GeoNutzV-style attribution terms. Official source: `https://opendata.dwd.de/weather/radar/radolan/rw/`. | Staging recipe exists and local downloaded payload traces are present. | Process/verify first if the user confirms the local payloads can be used. This is the cleanest near-term non-64 candidate. |
| 2 | `gwosc_event_strain_f32` | 32 | Gravitational-wave detector strain time series, one detector/event strain segment per sample. | GWOSC public open data; source/API: `https://gwosc.org/api/`. | Not currently staged. Need confirm direct text or simple binary payload path to avoid HDF5 dependency. | Strong variety. Prefer exact URL discovery for this before accepting another audio or image dataset. |
| 3 | `nasa_pds_sharad_radargram_i16` | 16 | Mars SHARAD radargram image products, one radargram per PDS product. | NASA PDS public planetary data. Source: `https://pds-geosciences.wustl.edu/missions/mro/sharad.htm`. | Staging exists; source discovery previously lacked direct products. | Strong variety if exact PDS label/payload URLs are found. |
| 4 | `usgs_3dep_las_intensity_u16` | 16 | Airborne LiDAR point intensity streams, one LAS tile intensity vector per sample. | USGS 3DEP public data / U.S. government work. | Staging exists but sampled public bucket objects were `.laz`, not `.las`. | Strong variety but blocked unless exact uncompressed `.las` URLs are found; do not add a LAZ decoder dependency. |
| 5 | `usgs_chirp_segy_i16` | 16 | Marine sub-bottom seismic traces, one SEG-Y trace/file natural boundary depending on product layout. | USGS public data / U.S. government work. | Prior script failed with no candidate URLs. | Strong variety only with exact SEG-Y URLs and strict format-code-3 int16 validation. |
| 6 | `noaa_nexrad_level2_moments_i16_or_u8` | 8/16 | Weather radar radial moment data, one station-volume or one moment sweep per sample. | NOAA/NCEI public data; AWS Open Data registry and NCEI NEXRAD Level-II. | Candidate previously listed; not accepted. Parser complexity is the main risk. | Strong variety relative to station weather and gridded rasters if parser stays clean. |
| 7 | `noaa_passive_acoustic_pcm16` | 16 | Long underwater passive-acoustic WAV recordings, one recording per sample. | NOAA/NCEI public data. Source family: `https://www.ncei.noaa.gov/products/passive-acoustic-data`. | Prior staged target existed conceptually but exact WAV URLs still need discovery. | Medium variety. More defensible than NSynth because recordings are long environmental instrument data, but still waveform audio. |
| 8 | `sdss_corrected_frame_fits_i16` | 16 | Astronomical CCD corrected imaging frames, one FITS frame per sample. | SDSS public data with citation/publication policy. Source: `https://www.sdss.org/`. | Staging exists; previous URL attempt produced no payload. | Medium variety. Do after radargram/LiDAR/strain unless exact URLs are easy. |
| 9 | `nasa_sdo_aia_synoptic_fits_i16` | 16 | Solar EUV/UV FITS images, one FITS image per sample. | NASA open data / SDO public data. Sources include SDO data access and NASA data policy. | Staging exists, but current route only found catalog/page artifacts, not FITS payloads. | Medium variety. Do not accept alongside SDSS unless both are especially clean and bounded. |
| 10 | `nsynth_test_notes_i16` | 16 | Musical instrument note waveforms, one PCM16 WAV note per natural sample. | NSynth documentation states Creative Commons Attribution 4.0. Official source: `https://magenta.withgoogle.com/datasets/nsynth`. | Staging recipe exists and the test archive appears locally present. | Deprioritize. Valid material, but too close to accepted audio waveform datasets and fixed-size. |

## Lower-Priority Or Conditional Candidates

| source | width | reason to keep conditional |
|---|---:|---|
| BBBC microscopy image sets | 8/16 | Useful microscopy domain, but per-image-set license and exact direct payload inventory must be confirmed before scripting. Previous policy already excluded broad BBBC guesses. |
| NASA AVIRIS classic hyperspectral ENVI cubes | 16 | Excellent shape if exact HTTPS payload URLs are found. Prior discovery produced FTP links and unusable source discovery. |
| NASA PDS CRISM TRDR cubes | 16 | Excellent planetary hyperspectral shape if exact labels/payloads are found. Prior attempts produced 404/no-label failures. |
| USGS sidescan sonar TIFF rasters | 8/16 | Potentially novel marine sonar imagery, but many products are 8-bit or compressed TIFF. Needs exact URLs and strict TIFF preflight. |
| MIDI event streams from public-domain/CC music archives | 8/16/32 | Novel symbolic-music event shape, but previous Mutopia archive selection produced empty selection. Needs a better exact-file list and must avoid arbitrary local tokenization. |

## Rejections For This Pass

| source | reason |
|---|---|
| More Binance variants | Strong source, but already heavily represented and primarily 64-bit market microstructure. |
| More NASA POWER/Open-Meteo/NOAA station tables | Too close to existing weather/climate scalar time-series families. |
| More SEC/World Bank/FRED/OWID indicators | Overrepresented table/indicator material, mostly 32/64-bit but low shape novelty. |
| KITTI/Waymo/autonomous-driving point clouds | Useful shape, but common licenses are non-commercial or otherwise not clearly acceptable for this collection. |
| CMU motion-capture ASF/AMC | Interesting motion trajectories, but license/use terms are not confirmed as permissive enough. |
| Poly Haven EXR half-float HDRI | Source/license are good and local payloads exist, but OpenEXR compression needs a real decoder. Do not write brittle partial decoders. |

## Recommended Next Step

Start with `dwd_radolan_rw_precip_i16` only if we want a near-term local win.
It is varied enough to be defensible, but it is not the strongest shape novelty
because raster datasets already exist.

For stronger diversity, prioritize exact URL discovery for:

1. `gwosc_event_strain_f32`
2. `nasa_pds_sharad_radargram_i16`
3. `usgs_3dep_las_intensity_u16`
4. `usgs_chirp_segy_i16`
5. `noaa_nexrad_level2_moments_i16_or_u8`

Do not spend the next round on `nsynth_test_notes_i16` unless the objective is
specifically to broaden audio. It is less varied than the stronger candidates
above despite being locally available.
