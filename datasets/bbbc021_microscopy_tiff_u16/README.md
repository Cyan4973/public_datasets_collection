# BBBC021 Fluorescence Microscopy TIFF UInt16

Collects raw fluorescence microscopy TIFF images from Broad Bioimage Benchmark Collection BBBC021 (human U2OS cells, drug screening) and emits one native uncompressed 16-bit grayscale TIFF raster per image.

BBBC021 provides per-field, per-channel microscopy images (e.g., DAPI, Tubulin, Actin) as 16-bit TIFFs inside archives. The build preserves natural image boundaries: one source TIFF = one sample, no tiling or concatenation.

This adds cell-biology fluorescence microscopy domain, distinct from CT X-ray (`tcia_nsclc_radiomics_ct_i16`), depth camera (`tum_rgbd_depth_u16`), masks (`bbbc038_nuclei_masks_u8`), and satellite rasters.

```bash
bash staging/bbbc021_microscopy_tiff_u16/download.sh
bash staging/bbbc021_microscopy_tiff_u16/build.sh
bash staging/bbbc021_microscopy_tiff_u16/verify.sh
```

Optional exact URLs:

```bash
BBBC021_URLS_FILE=/path/to/urls.txt staging/bbbc021_microscopy_tiff_u16/download.sh
```

Expected scale: 100-200 images bounded to <1 GB raw, median image >1k values (typically 1024x1280).

License: BBBC public dataset terms, academic research use, citation required. Preserve source attribution.

Parser: `tools/numeric16_extract.py --format tiff` — rejects compressed, 8-bit, RGB.
