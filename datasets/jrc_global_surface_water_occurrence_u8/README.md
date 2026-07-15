# JRC Global Surface Water Occurrence UInt8

Candidate `uint8` recipe for Joint Research Centre Global Surface Water
occurrence rasters.

The target material is the source-native occurrence byte plane: values `0..100`
represent water occurrence percentage and `255` represents no data. Natural
samples are selected internal GeoTIFF/COG tiles from official 10-degree source
rasters, decoded losslessly to raw byte grids.

Run:

```bash
bash staging/jrc_global_surface_water_occurrence_u8/download.sh
```

The default selection fetches bounded leading byte ranges from a fixed set of
public Google Cloud Storage URLs. The current occurrence GeoTIFFs are small
enough that those ranges usually contain the full compressed TIFF object; when
that happens, the script extracts selected internal tile chunks from the cached
local file without additional range requests. If a default URL changes upstream,
provide a tab-separated override file with `source_id` and `url` columns:

```bash
GSW_URLS_FILE=/path/to/source_urls.tsv bash staging/jrc_global_surface_water_occurrence_u8/download.sh
```
