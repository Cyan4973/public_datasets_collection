# Google AlphaEarth Satellite Embedding Tiles Int8 — 2026-08-28

## Outcome

`google_alphaearth_satellite_embeddings_i8` adds 384 native signed-int8
1024-by-1024 spatial grids containing 402,653,184 values. Six annual source
COGs each contribute all 64 learned embedding axes at one aligned geographic
tile. Median and fixed sample size are 1,048,576 values.

## Why this is new

The accepted 8-bit corpus already contains raw photographs, scientific image
planes, satellite classification masks, fire and water products, and tabular
Landsat features. It did not contain dense learned geospatial latent fields.
AlphaEarth's axes encode annual surface-condition trajectories inferred from
multiple Earth-observation sensors. They are therefore structurally and
semantically distinct from both ordinary imagery and categorical remote-sensing
rasters.

The 64 axes remain separate homogeneous streams. They are never interleaved,
and the recipe does not expand the official quantized bytes into artificial
float32 values.

## Source and license

Google's official Earth Engine catalog, STAC collection record, and GCS guide
identify the Satellite Embedding V1 Annual dataset and explicitly license it
under CC BY 4.0. The required attribution is:

> The AlphaEarth Foundations Satellite Embedding dataset is produced by Google
> and Google DeepMind.

The official guide documents signed-int8 values, `-128` NoData, 64 axes, and
the public `gs://alphaearth_foundations` distribution. The live Google
Developers HTML contains dynamic nonces and serialized UI ordering, so the
recipe validates stable semantic statements and records retrieved hashes rather
than pinning whole-page HTML hashes.

## Bounded source selection

The official geographic indexes range from about 34 MB to 798 MB and were not
needed for acquisition. Metadata-only GCS listings covered six fixed year and
UTM-zone prefixes. Within each prefix, the 75th-percentile object by compressed
size was selected to avoid tiny mostly-empty boundary COGs without selecting
the single largest object.

The resulting generation-pinned sources span Australia, western and eastern
North America, West Africa, South Asia, and eastern South America across
2020-2025. The complete upstream objects total 18,190,621,867 bytes, but the
recipe never downloads them wholesale.

## TIFF representation and extraction

Every selected source is a little-endian BigTIFF with an 8192-by-8192 primary
image, 64 signed-int8 samples per pixel, separate planar storage, 1024-by-1024
internal tiles, Zstandard compression (`Compression=50000`), and no horizontal
predictor. Each file therefore contains 4096 independently compressed chunks:
64 spatial tiles for each of 64 axes.

The embedded GeoTIFF projected CRS is checked against each source path. This
identified the selected EPSG:32631 object as West Africa; the UTM zone alone
would also encompass western Europe and was not used as a geographic claim.

The downloader validates exact GCS generation and full source size from HTTP
headers. It evaluates a fixed sequence of interior positions using only TIFF
compressed byte counts and chooses the first nontrivial position. All six
sources selected tile `(3,3)`. The same spatial tile is then range-fetched from
all 64 planes. The 384 compressed chunks total 206,815,823 bytes and decode to
402,653,184 source-native bytes.

## Verification

Build and verification passed on 2026-08-28. The independent verifier decodes
every source chunk again with the standalone Zstandard decoder and requires
exact byte equality with every emitted sample. It also confirms:

- six sources and exactly 64 axes per source;
- one shared tile coordinate across all axes of each source;
- 384 unique one-megabyte sample payloads;
- signed-int8 metadata and corpus little-endian declaration;
- no constant or structurally degenerate samples;
- zero `-128` NoData values in the accepted tiles; and
- 29-150 distinct signed values per sample, with median 109.

No GDAL, libtiff, NumPy, cloud account, or Earth Engine authentication is
required.
