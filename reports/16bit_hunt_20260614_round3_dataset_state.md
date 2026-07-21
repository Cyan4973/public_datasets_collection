# 16-bit Hunt Round 3 Dataset State

Historical report. For current machine-readable dispositions, consult
`attempts/dataset_status.tsv` before treating any failed/deferred row here as a
candidate to run.

The user ran `staging/source_variety_batch_20260614_16b/download.sh` after the proxy fix. Two candidates downloaded payloads during the original run. `tcia_nsclc_radiomics_ct_i16` was promoted to `datasets/` as accepted-but-low-variety material. A later focused retry repaired and promoted `smithsonian_openaccess_gltf_indices_u16`.

Acceptance floor used here: at least `10,000` primary values or `100 KB` primary sample bytes, median primary sample size at least `1,000` values, and accepted primary output at most `1,000,000,000` bytes.

## Summary

| dataset_id | download | build / verify | primary samples | primary bytes | sample size distribution | status |
|---|---|---|---:|---:|---|---|
| `tcia_nsclc_radiomics_ct_i16` | ok, 6 zip series, 220,368,853 downloaded bytes | ok | 933 | 489,160,704 | all 524,288 bytes | accepted; viable but fixed-size |
| `smithsonian_openaccess_gltf_indices_u16` | ok, 24 selected assets, 535,917,752 downloaded bytes | ok | 3 | 1,799,928 | 599,952 / 599,976 / 600,000 bytes | accepted; small sample count but native mesh topology |
| `polyhaven_hdri_exr_f16` | ok, 12 EXR files, 27,733,964 downloaded bytes | failed | 0 | 0 | none accepted | deferred: source EXRs are compressed, no local OpenEXR decoder |
| `nasa_aviris_classic_hyperspectral_i16` | failed | not run | 0 | 0 | n/a | source discovery selected FTP links unusable in this environment |
| `usgs_sidescan_sonar_tiff_u16` | failed | not run | 0 | 0 | n/a | selected data.gov seed returned HTTP 404 |
| `usgs_chirp_segy_i16` | failed | not run | 0 | 0 | n/a | seed pages exposed no direct `.sgy` / `.segy` payload links |
| `nasa_pds_sharad_radargram_i16` | failed | not run | 0 | 0 | n/a | superseded: source later proved to be 32-bit float and was accepted as `nasa_pds_sharad_radargram_f32` |
| `nasa_pds_crism_trdr_i16` | failed | not run | 0 | 0 | n/a | seed page exposed no direct selected payload links |
| `usgs_3dep_las_intensity_u16` | failed | not run | 0 | 0 | n/a | registry page exposed no direct `.las` payload links |
| `noaa_passive_acoustic_pcm16` | failed | not run | 0 | 0 | n/a | product page exposed no direct WAV/archive payload links |

## Verified Dataset: `tcia_nsclc_radiomics_ct_i16`

Source downloads:

| metric | value |
|---|---:|
| downloaded archives | 6 |
| downloaded bytes | 220,368,853 |
| extracted DICOM files accepted | 933 |
| source series represented | 6 |

Built primary samples:

| metric | value |
|---|---:|
| primary samples | 933 |
| primary values | 244,580,352 |
| primary bytes | 489,160,704 |
| numeric kind | `uint16` |
| endianness | little |
| transfer syntax | `1.2.840.10008.1.2` implicit VR little endian |
| sample geometry | 2D raster |
| sample shape | `512 x 512` |
| min / p25 / median / p75 / max sample bytes | 524,288 / 524,288 / 524,288 / 524,288 / 524,288 |
| unique sample sizes | 1 |
| same-size fraction | 1.0 |

Slice counts by downloaded series archive:

| archive | slices |
|---|---:|
| `tcia_1.3.6.1.4.1.32722.99.99.122579228305950125697741604889110154168.zip` | 176 |
| `tcia_1.3.6.1.4.1.32722.99.99.134645872977266948002680323417926540760.zip` | 135 |
| `tcia_1.3.6.1.4.1.32722.99.99.138522260934437218114778023563031054616.zip` | 176 |
| `tcia_1.3.6.1.4.1.32722.99.99.151892721628078086288828092641057509441.zip` | 176 |
| `tcia_1.3.6.1.4.1.32722.99.99.320898527671900265039224224949289088459.zip` | 135 |
| `tcia_1.3.6.1.4.1.32722.99.99.71621653125201582124240564508842688465.zip` | 135 |

Natural boundary is one DICOM slice. The recipe does not concatenate slices; every sample is one source pixel plane copied from DICOM `PixelData`.

Weakness: all accepted samples have exactly the same shape and byte size. This is normal for CT series but should be considered by the trainer selector if fixed-size datasets need downweighting or mixing constraints.

## Verified Dataset: `smithsonian_openaccess_gltf_indices_u16`

Focused retry:

| metric | value |
|---|---:|
| API-discovered candidate URLs | 621 |
| downloaded files | 24 |
| downloaded bytes | 535,917,752 |
| accepted GLB source files | 3 |
| accepted native index accessors | 3 |

Built primary samples:

| metric | value |
|---|---:|
| primary samples | 3 |
| primary values | 899,964 |
| primary bytes | 1,799,928 |
| numeric kind | `uint16` |
| endianness | little |
| sample geometry | 1D mesh index accessor |
| min / median / max sample values | 299,976 / 299,988 / 300,000 |
| min / median / max sample bytes | 599,952 / 599,976 / 600,000 |
| unique sample sizes | 3 |
| same-size fraction | 0.333333 |

Natural boundary is one glTF primitive index accessor. The recipe rejects Draco-compressed GLB files, uint32 index accessors, strided accessors, sparse accessors, malformed GLB files, and ZIPs without GLB assets. Independent accessors are not concatenated.

Weakness: accepted output is only three natural samples, all from related Smithsonian deer skeletal models. It is still valid native 16-bit topology material and clears the floor materially, but source diversity within this recipe is narrow.

## Deferred / Failed Details

`polyhaven_hdri_exr_f16` downloaded 12 native EXR files successfully, but the local standard-library parser accepted none. The downloaded files are compressed OpenEXR assets: 11 use PIZ compression and 1 uses ZIP compression. Without a local OpenEXR decoder or a substantially larger custom decoder, extracting half-float pixels would be brittle. This is a tooling/dependency block, not a license or source-quality rejection.

`nasa_aviris_classic_hyperspectral_i16` reached source discovery but selected FTP payload links. FTP cannot be resolved/fetched in this environment through the available proxy path. The downloader has been tightened to ignore non-HTTP(S) links for future runs; this candidate needs exact HTTP(S) product URLs or a different AVIRIS mirror.

`usgs_sidescan_sonar_tiff_u16` failed because the selected data.gov seed returned HTTP 404. It needs a corrected USGS package page or exact TIFF URLs.

`nasa_pds_sharad_radargram_i16` was superseded after later repair work showed
the selected SHARAD radargram products are native 32-bit float, not 16-bit. Use
`nasa_pds_sharad_radargram_f32` instead.

`usgs_chirp_segy_i16`, `nasa_pds_crism_trdr_i16`,
`usgs_3dep_las_intensity_u16`, and `noaa_passive_acoustic_pcm16` did not expose
direct matching payload links from their seed pages. They need exact URL lists
before rerun; no local payload exists to evaluate.
