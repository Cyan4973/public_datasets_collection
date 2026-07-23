# 16-bit New Domains Hunt — 2026-07-22

Goal: identify public, permissively licensed numeric series with native 16-bit
payloads (`int16`, `uint16`, `float16`) whose generating process / instrument
/ domain is not already covered by the 12 accepted 16-bit datasets.

No dataset payloads were downloaded by the agent in this pass. All candidate
assessments are from metadata, parser feasibility, and known source URL families.

## Existing 16-bit Coverage (to avoid)

| dataset_id | bits | domain | instrument / process | natural sample |
|---|---|---|---|---|
| `citibike_2024_01_station_ids_u16` | u16 | urban transport | bike-share operational ID dictionary | trip list shard |
| `nyc_311_descriptor_u16` | u16 | civic ops | 311 category ID dictionary | monthly shard |
| `dwd_radolan_rw_precip_i16` | u16 operative / i16 view | weather radar | DWD RADOLAN composite radar words | 900x900 composite |
| `hyg_star_photometry_i16` | i16 | astronomy catalog | HYG star catalog millimag photometry | star catalog table (mmag) |
| `librispeech_dev_clean_i16` | i16 | speech audio | microphone PCM16 utterance FLAC | utterance |
| `nsynth_test_notes_i16` | i16 | music audio | NSynth instrument note WAV | note waveform 64000 @16kHz |
| `sentinel1_grd_measurement_u16` | u16 | space SAR | Sentinel-1 GRD amplitude DN | product band raster |
| `sentinel2_l2a_reflectance_cogs_u16` | u16 | optical satellite | Sentinel-2 L2A reflectance | band raster |
| `smithsonian_openaccess_gltf_indices_u16` | u16 | 3D graphics geometry | GLB mesh index accessor | mesh index accessor |
| `tcia_nsclc_radiomics_ct_i16` | u16 | medical CT | DICOM CT slice pixels | CT slice |
| `tum_rgbd_depth_u16` | u16 | depth sensing | Kinect depth sensor | depth frame |
| `hf_smolllm2_135m_safetensors_f16` | f16 | ML weights | safetensors BF16 tensors | tensor shard |

Also present as derived operational u16/i16 but not counted as distinct 16-bit
native domains: GHCN daily climate tables (i16), NOAA ISD lite (i16), Bike UCI counts (u16), Covertype cartographic (u16/i16), OpenAlex counts, etc.

Policy note: `remote-sensing rasters, terrain, land-cover, planetary rasters, images, label rasters, CT slices, depth frames, speech/audio` are listed as already well-represented in `reports/numeric_new_domains_hunt_20260715.md`. Additional variants in those families should only be admitted if the sensor/modality is materially different.

Therefore promising new material must be:

- underwater acoustic imaging (not space SAR)
- marine sub-bottom profiling (not quake waveform)
- marine bioacoustics hydrophone (different from speech/music)
- HDR lighting probes for CG (different from model weights, even though both f16)
- airborne imaging spectroscopy (hundreds of bands, not 13-band MSI)
- drone hyperspectral forest, airborne LiDAR intensity (lidar radiometry, not elevation raster)
- solar physics EUV imaging (not stellar catalog photometry)
- optical sky-survey CCD imaging (image vs catalog)
- planetary spectroscopy / radar (Mars/Venus/lunar)
- fluorescence microscopy raw 16-bit TIFF (cell biology, not mask PNG)
- industrial machinery vibration (rotating equipment diagnostics)
- neuroscience extracellular electrophysiology (int16 spiking)

## Candidate Inventory — 15 NEW 16-bit Series (different domains)

### Tier 1 — Already staged, blocked on URL discovery, but domain is fresh

These exist in `staging/` but need exact URL pinning. Domain novelty is high.

#### 1. `usgs_sidescan_sonar_tiff_u16` — underwater acoustic imagery
- **Domain:** marine geology / seafloor sidescan sonar backscatter
- **Bits:** u16 native uncompressed TIFF strip
- **Source format:** GeoTIFF / TIFF `SampleFormat=uint`, `BitsPerSample=16`
- **Natural record:** one sidescan mosaic TIFF (GLORIA 50m Gulf of Mexico etc)
- **Origin:** USGS CMGDS, `catalog.data.gov` GLORIA
- **License:** US Government Public Domain (USGS)
- **Homepage:** https://cmgds.marine.usgs.gov/ , https://catalog.data.gov/dataset/gmx-q16-tif-u-s-gulf-of-mexico-eez-gloria-sidescan-sonar-data-mosaic-16-of-16-acea-50-m-cl
- **Parser:** `tools/numeric16_extract.py --format tiff` — rejects compressed, RGB, multisample
- **Expected scale:** 10-30 mosaics, 100-800 MB total, each mosaic 100-500 MB source TIFF → 50-250 MB raw sample
- **Risk:** seed pages may expose JPEG or 8-bit TIFF only; needs landing-page scraping for `.tif` direct links
- **Why new:** underwater acoustic imaging, not spaceborne SAR, not depth camera

#### 2. `usgs_chirp_segy_i16` — marine sub-bottom seismic
- **Domain:** marine geophysics / chirp sub-bottom profiling
- **Bits:** i16 SEG-Y format code 3
- **Source format:** SEG-Y rev1, trace header sample count, binary header format code 3
- **Natural record:** one SEG-Y trace (not whole survey)
- **Origin:** USGS DS 311,259,620,526,653, CMGDS DH_Seismic, CCB
- **License:** US PD
- **Homepage:** https://pubs.usgs.gov/ds/653/segy/ etc.
- **Parser:** `numeric16_extract.py --format segy` — accepts only format 3
- **Expected:** bounded 5-10 SEG-Y files, each 50-300 MB, 1000s traces per file → 100+ MB primary
- **Risk:** proxy blocks `pubs.usgs.gov`; needs explicit `USGS_CHIRP_SEGY_URLS_FILE`
- **Why new:** sub-bottom sediment stratigraphy, distinct from teleseismic waveforms (`seismic_waveform_i32`)

#### 3. `noaa_passive_acoustic_pcm16` — hydrophone bioacoustics
- **Domain:** marine bioacoustics / passive acoustic monitoring
- **Bits:** i16 PCM WAV
- **Source format:** WAV PCM16 mono/stereo, 8-96 kHz hydrophone
- **Natural record:** one WAV recording (10 min - 2 hr)
- **Origin:** NOAA NCEI passive acoustic data
- **License:** US DOC/NOAA public domain
- **Homepage:** https://www.ncei.noaa.gov/data/passive-acoustic-data/
- **Parser:** `numeric16_extract.py --format wav` (stdlib `wave`)
- **Expected:** 10-20 WAVs capped <1 GB total, median sample >>1000 values
- **Risk:** audio already represented, so justification must stress hydrophone vs speech/music; keep only if recordings are long natural habitat
- **Why new:** underwater soundscape, marine mammal, shipping noise — operational bioacoustics

#### 4. `usgs_3dep_las_intensity_u16` — airborne LiDAR radiometry
- **Domain:** airborne laser scanning intensity (reflectance at 1064 nm)
- **Bits:** u16 LAS point intensity field (12-13 byte offset per point record)
- **Source format:** LAS 1.2-1.4 uncompressed `.las` (NOT `.laz`/COPC)
- **Natural record:** one LAS tile intensity vector in point order
- **Origin:** USGS 3DEP `usgs-lidar-public` S3 bucket listable
- **License:** US PD
- **Homepage:** https://usgs-lidar-public.s3.amazonaws.com/
- **Parser:** `numeric16_extract.py --format las` — rejects LAZ
- **Expected:** 5-15 tiles, each tile 10-100 M points → 20-200 MB intensity per tile
- **Risk:** public bucket currently exposes mostly `.laz` EPT, not `.las`; needs exact uncompressed `.las` keys
- **Why new:** lidar reflectance photometry, distinct from elevation raster (`skadi_srtm_hgt` i16) and depth camera (u16)

#### 5. `polyhaven_hdri_exr_f16` — computer-graphics HDRI lighting
- **Domain:** photorealistic rendering / HDR environment lighting probes
- **Bits:** f16 half-float OpenEXR HALF channel
- **Source format:** OpenEXR scanline uncompressed HALF
- **Natural record:** one HDRI channel plane (e.g., R/G/B)
- **Origin:** Poly Haven CC0 HDRIs
- **License:** CC0 1.0 — fully permissive
- **Homepage:** https://polyhaven.org/hdris
- **Parser:** `numeric16_extract.py --format exr` — accepts only compression=0 and pixelType=1
- **Expected:** 4-12 HDRIs, each 2k×1k to 8k×4k, 3 channels → 8-96 MB per plane, 100-500 MB total
- **Risk:** Poly Haven may serve ZIP-compressed EXR only (needs zlib/PXR24 decode) → current parser would reject; needs exact uncompressed assets or decoder extension
- **Why new:** graphics lighting capture process (multi-exposure stitching with 360 camera), distinct from ML weight tensors despite both being f16

#### 6. `nasa_sdo_aia_synoptic_fits_i16` / `nasa_sdo_aia_fits_i16` — solar EUV
- **Domain:** heliophysics / solar atmosphere EUV imaging
- **Bits:** i16 FITS BITPIX=16
- **Source format:** FITS primary HDU, simple 2D image
- **Natural record:** one FITS synoptic AIA frame (e.g., 1024×1024)
- **Origin:** NASA SDO AIA via data.gov catalog / JSOC
- **License:** NASA open data, public domain US gov work
- **Homepage:** https://sdo.gsfc.nasa.gov/data/ , SDO data.gov package
- **Parser:** stdlib FITS parser (BITPIX check) in `sdss_corrected_frame` style
- **Expected:** 8-20 frames capped 500 MB/file, total <1 GB
- **Risk:** data.gov catalog search previously returned HTML landing pages, not direct FITS URLs; needs JSOC direct index
- **Why new:** solar EUV telescope, 10+ wavelength channels monitoring coronal plasma — distinct from night-sky optical and star catalog

### Tier 2 — New 16-bit domains not yet staged but feasible with existing tooling

#### 7. `nasa_aviris_classic_hyperspectral_i16` (already staged but worth fixing)
- **Domain:** airborne imaging spectroscopy (vegetation stress, minerals)
- **Bits:** i16/u16 ENVI cubes, interleave BIP/BIL/BSQ
- **Source format:** ENVI `.hdr` + raw binary, `data type = 2 or 12`, `samples, lines, bands`
- **Natural record:** one ENVI scene cube (e.g., 512×512×224)
- **Origin:** NASA/JPL AVIRIS Classic free data
- **License:** NASA public domain
- **Homepage:** https://aviris.jpl.nasa.gov/
- **Parser:** `numeric16_extract.py --format envi`
- **Expected:** 2-5 scenes bounded to <1 GB
- **Risk:** JPL site uses FTP-era links; needs exact HTTPS ENVI URLs
- **Why new:** 224-band hyperspectral, not 13-band Sentinel-2 multispectral; spectroscopy vs reflectance

#### 8. `zenodo_forest_hyperspectral_envi_i16` (staged)
- **Domain:** drone hyperspectral forestry
- **Bits:** i16/u16 ENVI
- **Source format:** ENVI over Lithuanian forests, DJI + hyperspectral camera
- **Natural record:** one drone flight cube
- **Origin:** Zenodo record(s) CC-BY-4.0
- **License:** CC-BY-4.0 / CC0 filtered only
- **Parser:** envi
- **Risk:** Zenodo API 403 in prior env; needs exact record IDs + direct file URLs
- **Why new:** UAV low-altitude forest pathology, distinct from airborne AVIRIS altitude and platform

#### 9. `nasa_pds_crism_trdr_i16` — Mars hyperspectral mineralogy (staged)
- **Domain:** planetary imaging spectroscopy / Mars mineral mapping
- **Bits:** i16 PDS3 QUBE/IMAGE `SAMPLE_BITS=16`
- **Source format:** PDS3 label `^QUBE` or `^IMAGE` detached `.qub`/`.img`, core items
- **Natural record:** one CRISM TRDR product cube
- **License:** NASA PDS public
- **Homepage:** https://pds-geosciences.wustl.edu/missions/mro/crism.htm
- **Parser:** pds3
- **Expected:** 6 products capped <1 GB total
- **Risk:** PDS volume index layout varies; needs pinned `mrocr_000x` label URLs via `CRISM_URLS_FILE`
- **Why new:** Martian surface mineralogy from orbit, hyperspectral 544 bands — planetary spectroscopy vs Earth remote sensing

#### 10. `sdss_corrected_frame_fits_i16` — optical sky-survey CCD imaging
- **Domain:** extragalactic optical astronomy survey imaging
- **Bits:** i16 FITS `BITPIX=16` corrected frame
- **Origin:** SDSS DR17 `frame-*.fits.bz2`
- **License:** SDSS public, permissive academic redistribution
- **Homepage:** https://data.sdss.org/, https://www.sdss.org/
- **Parser:** FITS BITPIX=16 check, bz2 decompress
- **Expected:** 40 frames default, each ~10 MB compressed → 25 MB raw → ~1 GB cap needs `FILE_LIMIT`
- **Risk:** SDSS directory listings returned 503 in prior hunt; needs exact stable frame URLs
- **Why new:** raw CCD imaging survey (photons), distinct from `hyg_star_photometry_i16` which is catalog millimag values

### Tier 3 — Fresh proposals not yet staged (write new staging recipes for these)

#### 11. `bbbc_microscopy_raw_tiff_u16` — fluorescence cell microscopy raw
- **Proposal ID:** `bbbc021_microscopy_tiff_u16` or `bbbc039_microscopy_tiff_u16`
- **Domain:** cell biology / high-content fluorescence microscopy
- **Bits:** u16 TIFF uncompressed 16-bit grayscale fluorescence (not mask PNG)
- **Source format:** TIFF 16-bit `SampleFormat=uint`, single sample, e.g., BBBC021 16-bit cytoplasm/nuclei
- **Natural record:** one raw microscopy image (e.g., 1024×1280)
- **Origin:** Broad Bioimage Benchmark Collection — https://bbbc.broadinstitute.org/BBBC021 etc.
- **License:** BBBC public terms, citation required, research use permissive (check per-image: most BBBC sets are CC-BY or free for research)
- **Homepage:** https://bbbc.broadinstitute.org/BBBC021
- **Parser:** `numeric16_extract.py --format tiff` — already handles 16-bit TIFF
- **Expected:** BBBC021: 13,200 images? But bounded subset 100-200 images → 200-500 MB total, median >1k values easily
- **Risk:** some BBBC sets are 8-bit; must preflight with `tiff_values` bits check; also need to differentiate raw vs mask
- **Why new:** fluorescence microscopy photon counting, distinct from mask u8, CT u16, depth u16, satellite u16 — instrument is widefield fluorescence microscope with chemical staining, biological process

#### 12. `neon_aop_hyperspectral_envi_u16` — NEON airborne observatory hyperspectral
- **Proposal ID:** `neon_aop_hsi_tiles_u16`
- **Domain:** ecosystem ecology / airborne imaging spectroscopy for vegetation traits
- **Bits:** u16 ENVI or HDF5? NEON L1 radiance ENVI: typical `data type 12` uint16
- **Source format:** NEON AOP L1 hyperspectral reflectance mosaics ENVI `.dat`+`.hdr` or HDF5 with 426 bands
- **Natural record:** one flightline tile hyperspectral cube
- **Origin:** NEON data portal https://data.neonscience.org/data-products/DP3.30006.001 etc.
- **License:** CC BY 4.0 (NEON data)
- **Homepage:** https://data.neonscience.org/
- **Parser:** envi (if ENVI variant) — otherwise needs HDF5 tooling not allowed, so pick ENVI reflectance tiles only
- **Expected:** 2-4 tiles bounded <1 GB
- **Risk:** NEON portal requires API token? Some files need Earthdata auth; must find direct S3 public mirror `neon-aop` bucket; also some products are HDF5 float32 not int16
- **Why new:** ecological observatory systematic continental-scale vegetation spectroscopy — operational ecosystem monitoring, not mineral exploration (AVIRIS)

#### 13. `cwru_bearing_vibration_i16` — industrial rotating-machinery vibration
- **Proposal ID:** `cwru_bearing_vbr_i16`
- **Domain:** predictive maintenance / rotating machinery diagnostics
- **Bits:** i16 accelerometer time series (native ADC 16-bit) stored as float64 in .mat but source ADC is int16; to stay `native_numeric`, we must emit decoded MATLAB `double` array as derived_operational_numeric? Better to find true PCM16 wav export or int16 raw — CWRU also provides time series as 16-bit? Alternative: use `Paderborn University Bearing Dataset` which provides vibration as 16-bit? Or use `MFPT` dataset?
- **Alternative cleaner:** `mfpt_bearing_vibration_i16` — MFPT Society bearing data originally PCM? Actually MFPT provides `.mat` double too.
- **Simpler feasible:** `paderborn_bearing_vibration_i16` — Paderborn dataset provides `.mat` with `double` but original is int16.
- **Parser feasibility:** MATLAB v5 .mat parser needed; repo currently forbids heavy deps but python stdlib can parse uncompressed MAT array with simple struct — need custom parser, not impossible but adds tooling.
- **Source format:** MATLAB v5 `miDOUBLE` array dimensions `[samples,1]` at 64 kHz
- **Natural record:** one bearing condition recording (e.g., normal, inner race fault, outer race)
- **License:** CWRU academic free, Paderborn academic free — need explicit permissive license check
- **Why new:** industrial vibration / accelerometry, continuous electromechanical monitoring — distinct from acoustic audio, seismic, EEG

#### 14. `openneuro_ieeg_electrophys_i16` — intracranial EEG / Neuropixels extracellular
- **Domain:** neuroscience / intracranial electrophysiology
- **Bits:** i16 extracellular voltage traces
- **Source format:** EDF `EDF+` with digital int16, or NWB HDF5 with int16. EDF is parseable with python edf reader already used for `eeg_physionet`.
- **Natural record:** one iEEG channel trace or one Neuropixels probe shank recording
- **Origin:** OpenNeuro ds003029 etc., or Allen Brain Observatory Neuropixels Visual Coding
- **License:** CC0 / CC-BY for OpenNeuro; Allen Institute terms permissive academic
- **Homepage:** https://openneuro.org/, https://portal.brain-map.org/
- **Parser:** For EDF: reuse `eeg_physionet` EDF parser (needs extension); for NWB HDF5 would need h5py not allowed → prefer EDF iEEG datasets
- **Expected:** 10-20 EDF files, each multi-channel but emit per-channel trace? Natural record kind should remain file-level unless channel grouping justified
- **Risk:** EDF files are often multi-channel >100 MB; need bounded file count; also many iEEG datasets are 16-bit native but physical conversion uses gain
- **Why new:** invasive brain recordings, high-frequency spiking, distinct from scalp EEG variance (chbmit) and ECG

#### 15. `fastmri_knee_mri_i16` — medical MRI raw k-space or DICOM 16-bit
- **Domain:** medical MRI / knee imaging (different modality from CT)
- **Bits:** i16/u16 DICOM MR image pixels or raw k-space int16
- **Source format:** DICOM MR `BitsAllocated=16` or HDF5 complex int16 fastMRI singlecoil
- **Natural record:** one MR slice or one k-space slice
- **Origin:** fastMRI https://fastmri.med.nyu.edu/ knee dataset (1.6k volumes) or TCIA MR datasets
- **License:** fastMRI MIT license + physionet? Actually fastMRI CC-BY 4.0? Check — NYU fastMRI dataset is CC-BY 4.0 with research use
- **Parser:** `numeric16_extract.py --format dicom` for DICOM MR; HDF5 would need h5py
- **Risk:** fastMRI raw is HDF5 complex needing h5py; easier to use TCIA MR DICOM such as `tcia_brain_mri_u16`
- **Why new:** magnetic resonance physics (RF excitation, T1/T2 weighting) vs X-ray attenuation CT — different generation process, still 16-bit medical

## Focused Action Plan

### Immediate runnable (no new code needed, only exact URL files)

1. **Pin exact URLs for `usgs_sidescan_sonar_tiff_u16`**
   - Create `staging/usgs_sidescan_sonar_tiff_u16/urls.txt` with 10-20 direct TIFFs from CMGDS GLORIA pages.
   - Use `bounded_url_download.py` with `--suffix .tif --max-files 20`
   - Build: `python3 tools/numeric16_extract.py build ... --format tiff`
   - Expected status: ok if TIFFs are uncompressed 16-bit

2. **Pin `usgs_chirp_segy_i16` URLs**
   - Use `https://pubs.usgs.gov/ds/653/segy/` directory listing — enumerate `.sgy` files via script, write to `urls.txt`
   - Avoid proxy block by testing from user env: `curl -L https://pubs.usgs.gov/ds/653/segy/ | grep sgy`
   - Build: `--format segy`

3. **Test Poly Haven CC0 HDRI direct links**
   - Poly Haven API: `https://api.polyhaven.com/files/<asset>` returns download URLs; need uncompressed EXR detection
   - Write `ASSET_LIMIT=4` download, attempt build, inspect `extracted/*/openexr` header compression byte
   - If ZIP compression only, propose adding minimal zlib PXR24 decoder to `numeric16_extract.py` or switch to another CC0 HDRI source that offers NONE compression (e.g., HDRI Haven old)

### New recipes to write (Tier 3)

Create staging directories:

- `staging/bbbc021_microscopy_tiff_u16/` — BBBC021 fluorescence TIFF raw
- `staging/neon_aop_hyperspectral_envi_u16/` — NEON AOP L1 ENVI uint16
- `staging/cwru_bearing_vibration_i16/` — bearing vibration with custom MATLAB parser, or switch to `mfpt_bearing` which provides CSV float but original int16 warranted as derived_operational_numeric if documented

Each new recipe must include:
- `manifest.toml` with `source_format`, `source_field`, `natural_record_kind`, `role=primary`, `representation_class=native_numeric` (or derived_operational_numeric for CWRU if source is double wrapper of int16 ADC)
- `README.md` with bounded scope and run instructions
- `download.sh` rejecting non-16-bit pre-download via header check where possible
- `build.sh` calling `numeric16_extract.py` or custom Python that respects median floor and rejects constant samples
- `verify.sh` rejecting degenerate, checking missing-value policy alignment

### Validation gates

- All primary payloads must be decoded typed values, not opaque bytes (collection_protocol hard rule 3)
- Acceptance floor: >=10k values, >=100KB, median >=1k values, <=1GB
- Natural record boundary respected: e.g., per TIFF mosaic, per SEG-Y trace, per microscopy image, per WAV file (not concatenated)
- License: US PD, CC0, CC-BY, CC-BY-SA are acceptable; ambiguous "academic only" must be flagged and rejected if not permissive

## Domain Distance Justification Summary

| new candidate | distance from existing 16-bit | material difference |
|---|---|---|
| sidescan sonar | Sentinel1 is space SAR (microwave backscatter from orbit), sidescan is underwater 100 kHz acoustic backscatter from towed fish; propagation medium different (water vs vacuum/atmosphere), platform different | marine acoustic imaging |
| chirp segy | seismic_waveform_i32 is teleseismic earthquake body waves at 20-100 Hz recorded by broadband seismometer on land; chirp is high-frequency 1-20 kHz sub-bottom profiler from ship, imaging sediment layers | marine geophysics |
| passive acoustic | librispeech is human speech close-mic 16 kHz; nsynth is musical instrument note in anechoic chamber; passive acoustic is omnidirectional hydrophone in ocean, days-long soundscape, shipping + biotic | hydrophone bioacoustics |
| lidar intensity | skadi_srtm_hgt is elevation in meters from SRTM interferometry; tum_rgbd is active IR structured light depth; lidar intensity is 1064 nm laser reflectance strength, radiometry not range | lidar radiometry |
| hdri exr f16 | hf_smolllm2 is BF16 model weights (trained parameters); polyhaven is captured HDR photon flux via bracketing, physical scene luminance, half-float image plane | graphics lighting |
| AVIRIS hyperspectral | Sentinel2 is 13-band multispectral reflectance at 10-60 m with 12-bit quantized to 16; AVIRIS is 224 contiguous 10 nm bands airborne spectrometer measuring radiance, different sensor physics | imaging spectroscopy |
| forest drone hyperspectral | same as AVIRIS but UAV platform, low altitude 50 m vs 20 km, forestry disease vs mineralogy | precision forestry UAV |
| SDO AIA FITS | hyg photometry is catalog millimag numeric table; SDO is direct EUV CCD image of solar corona at 171Å, 193Å etc., plasma emission, not star | solar physics imaging |
| SDSS corrected frame | hyg is catalog; SDSS imaging is CCD drift-scan raw sky photons, de-biased, 2.5 m telescope | optical survey imaging |
| CRISM TRDR | Sentinel2 Earth observation; CRISM is Mars Reconnaissance Orbiter CRISM, 544 bands near-IR, mineral absorptions from another planet | planetary spectroscopy |
| BBBC raw microscopy | tcia CT is X-ray attenuation human lung; microscopy is fluorescence photon emission from stained cells, 100x microscope, cell biology | cell fluorescence microscopy |
| CWRU bearing | eeg_physionet is brain scalp potentials, microvolts; bearing is piezoelectric accelerometer on rotating machinery, kHz vibration, fault impact transients | industrial diagnostics |
| iEEG Neuropixels | chbmit variance is scalp EEG variance; iEEG is intracranial invasive, 30 kHz extracellular action potentials | invasive neurophysiology |
| fastMRI DICOM | CT uses X-ray; MR uses RF + magnetic gradient, proton spin relaxation | MR physics |

## What not to pursue (already well-covered)

- More Sentinel-2 / Landsat multispectral reflectance unless new sensor with materially different generation (AVIRIS hyperspectral is borderline okay because 224 bands vs 13)
- More weather radar composites (DWD already) — NEXRAD L2 moments deferred because too close
- More terrain DEM (SKADI already)
- More speech / music audio (LibriSpeech, NSynth already) — hydrophone is okay because different transducer and medium
- More CT slices (TCIA already) unless modality changes to MR, microscopy, etc.

## Deliverables from this hunt

- This report at `reports/16bit_new_domains_hunt_20260722.md`
- Proposed priority for user-run download attempts:
  ```bash
  bash staging/usgs_sidescan_sonar_tiff_u16/download.sh
  bash staging/usgs_sidescan_sonar_tiff_u16/build.sh
  bash staging/usgs_sidescan_sonar_tiff_u16/verify.sh

  bash staging/usgs_chirp_segy_i16/download.sh
  bash staging/usgs_chirp_segy_i16/build.sh
  bash staging/usgs_chirp_segy_i16/verify.sh

  bash staging/noaa_passive_acoustic_pcm16/download.sh
  bash staging/noaa_passive_acoustic_pcm16/build.sh
  bash staging/noaa_passive_acoustic_pcm16/verify.sh
  ```
- Two new staging skeletons to be created next: `bbbc_microscopy_raw_tiff_u16` and `neon_aop_hyperspectral_envi_u16` (deferred to follow-up turns to keep report concise and avoid speculative URLs)

## References

- Existing 16-bit hunt state: `reports/16bit_next_hunt_20260614_dataset_state.md`, `reports/16bit_hunt_20260614_dataset_state.md`
- Next-target triage: `reports/16bit_next_targets_after_validated_promotions_20260615.md`
- Error triage: `reports/16bit_hunt_20260615_error_triage.md`, `reports/16bit_next_hunt_error_triage_20260614.md`
- Hunt criteria: `reports/numeric_new_domains_hunt_20260715.md`
- Extract tool: `tools/numeric16_extract.py`
- Protocol: `collection_protocol.md`, `reports/protocol_case_law.md`

---
Generated 2026-07-22, no payloads downloaded, analysis only.
