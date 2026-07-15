# 8-bit Numeric New-Territory Candidates

Date: 2026-07-14

Goal: identify fresh `uint8` / byte-valued public numeric materials that are not already represented in the current accepted set or in prior successful 8-bit hunt reports. No dataset acquisition was performed for this review.

## Current Coverage To Avoid

Already represented in `datasets/` or prior successful 8-bit reports:

- small and medium image pixels: `mnist_px_u8`, `fmnist_px_u8`, `cifar10_pixels_u8`, `medmnist_pathmnist_images_u8`
- segmentation and label rasters: `coco_panoptic_val2017_labels_u8`, `msd_hippocampus_segmentation_labels_u8`, `esa_worldcover_landcover_tiles_u8`
- remote sensing / geospatial byte materials: `statlog_landsat_satellite_u8`, `nasa_pds_themis_ir_mosaic_u8`, `dc_lidar_2015_classification_u8`, prior `natural_earth_vector_shp_u8`, prior `geofabrik_liechtenstein_osm_pbf_u8`
- weather radar bytes: `noaa_nexrad_level3_products_u8`
- biology and medicine: `ena_fastq_quality_phred`, `encode_methylation_pct_u8`, `bam_read_mapq_u8`, `pfam_seed_alignments_u8`, prior `ncbi_refseq_viral_genomes_u8`
- audio and model/binary artifacts: `fsdd_pcm_u8`, `smollm2_135m_q8_gguf_weights`, prior `google_fonts_ofl_ttf_u8`

Also avoid replaying known failures: PASCAL VOC 2012 masks were rejected on license terms, several 28x28 / small-row UCI materials failed the natural-record floor, and raw symbolic remappings such as dependency labels or slot labels are out of scope.

## Best New Candidates

| rank | candidate id | new territory | primary `uint8` target | natural sample | why it adds variety | main risk |
|---:|---|---|---|---|---|---|
| 1 | `physionet_mitbih_annotation_codes_u8` | clinical event streams | official WFDB annotation symbol / type codes from MIT-BIH Arrhythmia Database records | one source record's annotation-code sequence | Adds sparse, irregular clinical event timing semantics rather than waveform samples; reuses a known permissive PhysioNet source family but a different material. | Must prove enough records exceed the median floor without concatenating records; keep signal samples out of this recipe to avoid duplicating existing MIT-BIH signal recipes. |
| 2 | `usda_cdl_crop_classes_u8` | agricultural land-use rasters | USDA Cropland Data Layer crop-class bytes | one official state/year raster tile or one internal GeoTIFF tile | Adds high-cardinality crop phenology / land-use classes, materially different from global land-cover tiles. | Full rasters are large; script needs bounded state/year selection and GeoTIFF tile/window handling under the 1 GB output cap. |
| 3 | `noaa_cdr_sea_ice_concentration_u8` | cryosphere concentration grids | NOAA/NSIDC sea-ice concentration packed byte grids | one daily or monthly hemisphere grid | Adds polar sea-ice percentage fields with strong seasonal and coastal structure. | Source packaging is often NetCDF; implementation may need strict local parsing or a dependency strategy. Missing and land codes must be preserved or rejected consistently. |
| 4 | `goes_abi_cloud_mask_u8` | geostationary atmosphere masks | GOES-R ABI cloud-mask / clear-sky-mask class bytes | one full-disk or CONUS scan product | Adds time-resolved atmospheric classification grids, distinct from static land-cover rasters and radar products. | NetCDF4/HDF5 product parsing is the hard part; keep one ABI product, sector, satellite, and bounded time window. |
| 5 | `bbbc038_nuclei_masks_u8` | microscopy cell morphology | source-provided nuclei / cell mask label bytes | one microscopy field mask image | Adds biological microscopy shape masks rather than natural images or medical volume labels. | License and source terms need explicit confirmation; some masks may be RGB, binary, or label IDs above 255, so the recipe must preserve only source-native 8-bit masks. |
| 6 | `jrc_global_surface_water_occurrence_u8` | surface-water climatology | Global Surface Water occurrence / seasonality byte grids | one official GeoTIFF tile or one internal COG tile | Adds hydrologic long-run occurrence percentages, not ordinary land-cover classes. | Large COGs need bounded range/tile extraction; avoid mixing occurrence, change, seasonality, and transitions in one recipe. |
| 7 | `noaa_ims_snow_ice_cover_u8` | operational snow and ice charts | IMS snow/ice category codes | one daily grid | Adds operational categorical cryosphere charts with weather-map cadence. | Upstream encodings vary by era and resolution; exact product/year selection must avoid mixing ASCII grids, GeoTIFFs, and GRIB variants unless the emitted primary target is identical. |
| 8 | `usgs_sidescan_sonar_tiff_u8` | marine acoustic imagery | uncompressed or losslessly decoded sidescan sonar grayscale bytes | one source sonar mosaic TIFF | Adds seafloor acoustic backscatter texture, not optical or radar imagery. | Needs exact permissive USGS product URLs and strict TIFF preflight; many candidate mosaics are compressed, 16-bit, or poorly documented. |
| 9 | `noaa_nexrad_level2_reflectivity_u8` | raw radar volumes | decoded Level-II reflectivity moment bins when the source moment is byte-coded | one sweep or one moment field from a station volume | Adds raw polar-volume radar structure, deeper than the accepted Level-III product-message byte recipe. | Parser complexity is high; mixed 8/16-bit moments and bzip2 block structure must be handled without treating compressed bytes as primary. |
| 10 | `modis_active_fire_mask_u8` | satellite fire detection | MODIS/VIIRS fire-mask class bytes from active-fire products | one source granule mask plane | Adds event-like thermal anomaly classification over swaths. | Many NASA products require Earthdata flow and HDF parsing; public/permissive access and exact native uint8 SDS fields must be verified before scripting. |

## Recommended First Pass

Start with `physionet_mitbih_annotation_codes_u8` and `usda_cdl_crop_classes_u8`.

`physionet_mitbih_annotation_codes_u8` is the smallest implementation surface because the repository already has PhysioNet/WFDB patterns, and annotation codes are official operational numeric labels rather than local remaps. The decision point is whether enough per-record annotation sequences clear the median-sample floor.

`usda_cdl_crop_classes_u8` is the strongest new raster target. It is still geospatial, but the material is agricultural crop classification, with much richer categorical structure than broad land-cover classes. It should be bounded by selected state/year rasters or by official internal GeoTIFF tiles.

Use `noaa_cdr_sea_ice_concentration_u8` third if NetCDF parsing is acceptable. It would add a genuinely new physical process and seasonal field structure.

## Lower-Priority Or Risky Ideas

- More photographic image datasets are valid `uint8`, but they do not add much beyond existing image coverage.
- More semantic segmentation benchmarks should be avoided unless the license is clearly permissive and the masks are source-native 8-bit; VOC has already failed this check.
- Raw compressed file bytes should not be used as a shortcut. Decode or preserve source-native numeric planes, records, or binary structures with meaningful boundaries.
- Tiny catalog booleans, month fields, quality flags, and helper masks should remain auxiliary unless the source material itself is a coherent operational numeric product.
