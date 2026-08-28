# Google AlphaEarth Annual Satellite Embedding Tiles Int8

This recipe collects native signed-int8 latent fields from the annual Google
AlphaEarth Foundations Satellite Embedding dataset. It contributes a structure
not otherwise present in the corpus: dense AI-derived geospatial embedding
planes rather than raw imagery, physical rasters, categorical masks, or model
parameter arrays.

The official COGs are little-endian BigTIFF files containing 64 learned axes,
`A00` through `A63`. Each axis is stored separately as signed int8 and divided
into independent Zstandard-compressed 1024-by-1024 tiles. The recipe preserves
these native bytes; it does not apply Google's optional float dequantization or
interleave axes.

Six generation-pinned COGs cover Australia, western and eastern North America,
West Africa, South Asia, and eastern South America across 2020-2025. Each
complete source is 2.7-3.2 GB, so `download.sh` uses bounded HTTP ranges:

- fetch a 4 MiB TIFF header from each source;
- validate signed-int8, 64-plane, planar, tiled Zstandard storage;
- choose the first qualifying location from a fixed sequence of interior tile
  positions using compressed sizes only to avoid empty boundary regions; and
- fetch the same spatial tile independently from all 64 axes.

The resulting family has 384 samples of exactly 1,048,576 values each, totaling
402,653,184 signed-int8 values (384 MiB). Every source contributes all 64 axes
at one aligned location. The accepted build has zero NoData values in selected
tiles and 29-150 distinct values per sample.

Run:

```sh
bash datasets/google_alphaearth_satellite_embeddings_i8/download.sh
bash datasets/google_alphaearth_satellite_embeddings_i8/build.sh
bash datasets/google_alphaearth_satellite_embeddings_i8/verify.sh
```

Requirements are `curl`, Python 3, and the standalone `zstd` command. No GDAL,
libtiff, NumPy, cloud account, or Earth Engine authentication is needed.

The downloader also checks each object's embedded WGS 84 UTM EPSG code against
its bucket path, preventing geographic labels from being inferred from the UTM
zone number alone.

The dataset is CC BY 4.0. Required attribution:

> The AlphaEarth Foundations Satellite Embedding dataset is produced by Google
> and Google DeepMind.
