# 8-bit Numeric Acquisition Candidates

Date: 2026-06-26

Goal: find new `uint8` / byte-oriented public datasets whose natural samples have a different shape from the current accepted set and can train compression models without relying on synthetic local remaps.

## Current Coverage To Avoid Duplicating

Already represented or staged nearby:

- 2D image pixels: `mnist_px_u8`, `fmnist_px_u8`, `cifar10_pixels_u8`, `medmnist_pathmnist_images_u8`
- medical / sensor byte sequences: `mitbih_arrhythmia_u8`, `fsdd_pcm_u8`, `ena_fastq_quality_phred`, `encode_methylation_pct_u8`
- machine artifacts and vector formats: `smollm2_135m_q8_gguf_weights`, `google_fonts_ofl_ttf_u8`, `natural_earth_vector_shp_u8`, `geofabrik_liechtenstein_osm_pbf_u8`
- nucleotide/text derivatives nearby: `ucsc_hg38_chromosomes_u8`, `ncbi_refseq_viral_genomes_u8`, `unicode_bmp_gutenberg`, `tokens_*_gutenberg`

Avoid short fixed-width tabular candidates unless the protocol changes. The rejected `uci_letter_recognition_u8` attempt showed why: a table row with 16 values is the natural record, so emitting column blocks hides the natural boundary.

## Best Next Candidates

| rank | candidate id | material shape | primary `uint8` target | why it adds variety | acquisition notes | main risk |
|---:|---|---|---|---|---|---|
| 1 | `pascal_voc2012_segmentation_masks_u8` | 2D categorical label masks | one segmentation PNG decoded to label bytes per mask | Unlike RGB images, values are semantic region IDs with large constant areas and object-boundary structure. | Use official PASCAL VOC 2012 `SegmentationClass` / `SegmentationObject` masks; decode indexed PNGs locally; one mask is one natural sample. | VOC usage terms must be checked before scripting; avoid if redistribution terms are not permissive enough. |
| 2 | `coco_panoptic_val2017_labels_u8` | large 2D/3D categorical segmentation maps | category-id or low byte of official panoptic PNG labels, one image mask per sample | Adds dense scene-layout label fields, very different entropy from photographic pixels. | Use COCO official annotations and val2017 panoptic PNGs; bounded validation split; decode PNGs locally. | Panoptic RGB IDs exceed 8 bits; using only category labels is a derived operational target and must be justified from official annotations. |
| 3 | `esa_worldcover_landcover_tiles_u8` | geospatial categorical raster tiles | land-cover class byte per pixel, one tile/window per sample | Adds remote-sensing classification maps rather than continuous reflectance or ordinary imagery. | Use ESA WorldCover public map tiles; select a bounded set of tiles across biomes; preserve class bytes. | GeoTIFF decoding may need GDAL unless exact COG/tile parsing is implemented or converted only after user-provided local tools. |
| 4 | `pfam_seed_alignments_u8` | variable-size biological multiple-sequence alignments | Stockholm/FASTA alignment character bytes, one family alignment per sample | Adds rectangular-ish symbolic matrices with gap structure, distinct from raw genome strings and FASTQ quality scores. | Use Pfam seed/full alignment gzip from the official FTP; keep alignment blocks above 1,000 bytes; write source alignment symbols unchanged. | License/provenance needs confirmation; many small families must be filtered without aggregating them. |
| 5 | `wikimedia_enwiki_xml_pages_u8` | long UTF-8 document records in XML dump | article text bytes, one page/revision text body per sample | Adds natural-language byte streams with long record boundaries; not token IDs or UTF-16 mirrors. | Use a bounded official pages-articles multistream shard; parse local bzip XML; keep pages whose text body is >= 1,000 bytes. | Text is not "numeric" in the usual sense; accept only if byte-stream training material is in scope. |
| 6 | `noaa_nexrad_level3_products_u8` | polar/radial weather-radar product grids | official 8-bit product bin values per sweep/product | Adds operational radar quantization and radial geometry, distinct from station time series and optical imagery. | Use NOAA public NEXRAD Level-III products with exact keys or a bounded date/station set; parse product blocks locally. | Parser complexity and product heterogeneity; must keep one coherent product code, not a mixed feed. |
| 7 | `usgs_3dep_las_classification_u8` | unordered point-cloud categorical labels | LAS point classification / return-count bytes, one tile per sample | Adds point-cloud categorical streams and acquisition-order structure. | Use public USGS 3DEP / Entwine Point Tiles or LAS/LAZ tiles; keep classification bytes from selected tiles. | LAZ decompression is not stdlib; LAS tiles may be large and exact public URLs need discovery. |

## Recommended First Pass

Start with `pascal_voc2012_segmentation_masks_u8` if the license check passes. It has the best balance of new shape, small implementation surface, and natural samples safely above the median floor. The PNG decoder can be stdlib-only for indexed/grayscale PNGs using `zlib`, and the verification criteria are straightforward: non-constant masks, `uint8`, natural sample = one mask, median pixels well above 1,000.

If VOC terms are not acceptable, use `pfam_seed_alignments_u8` next. It avoids image duplication and should be implementable with gzip/text parsing only, but it needs careful filtering so small families do not pass by concatenation.

## Rejected Or Low-Priority Ideas

- More MNIST/SVHN-like image datasets: valid `uint8`, but they do not add a new shape.
- UCI small-row feature tables: natural records are short rows and repeat the `uci_letter_recognition_u8` failure mode.
- More Project Gutenberg byte encodings: the repo already has Gutenberg UTF-16 and token-ID datasets; raw UTF-8 would be a width/encoding neighbor rather than a new material shape.
- More GHCN/CO-OPS weather flags as `uint8`: likely helper/categorical metadata, not a strong primary compression target.
- JPEG/PNG file bytes as primary payload: easy byte samples, but already-compressed source files are less useful for compression training than decoded labels, masks, rasters, or source binary formats with meaningful structure.
