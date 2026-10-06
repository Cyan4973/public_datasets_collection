# Global Seasonal Sentinel-1 Interferometric Coherence — summer VV COH12 (uint8)

Seasonal-median **12-day repeat-pass interferometric coherence** of Sentinel-1
C-band VV radar, from the *Global Seasonal Sentinel-1 Interferometric Coherence
and Backscatter Data Set* (Earth Big Data LLC and Gamma Remote Sensing AG, for
NASA JPL; Sentinel-1 IW SLC data from Dec 2019 to Nov 2020). The producer stores
each metric as one 1x1-degree, 3-arcsecond (~90 m) GeoTIFF per tile.

This recipe collects one metric only: `summer_vv_COH12` (June–August 2020,
VV polarization, 12-day temporal baseline). Each pixel is the producer's DN.
Per the bucket documentation, `gamma = DN / 100` with `gamma` in [0, 1], and
DN 0 is nodata, stored as unsigned 8-bit.

## Scope

- 150 tiles in one contiguous land-interior block: upper-left labels
  `N36..N45` x `W100..W114`, i.e. 35–45 N and 114–99 W. The block covers Utah,
  Colorado, Wyoming, southern Idaho and Montana, northern Arizona and New
  Mexico, and the western High Plains. That gives deserts, sagebrush steppe,
  forested mountains, dryland and irrigated agriculture, and a few lakes, which
  produce very different coherence distributions under one quantity.
- One sample per tile: a 1200 x 1200 uint8 raster (1,440,000 values), in
  row-major order, north to south and west to east. Tiles are neither tiled
  further nor merged.
- 150 samples, 216,000,000 primary bytes. Download: 161,185,497 bytes
  (865 KB–1.21 MB per file).
- The full bucket has 24,858 tile prefixes (about 35 GB for this metric
  globally), so a bounded block is required. About 100 MB is enough for
  downstream selection. The block is a natural geographic unit, sized a little
  above that.

The tile list, sizes, S3 ETags (single-part MD5) and Last-Modified dates are
pinned in `sources.tsv`. `discover.sh` documents how they were resolved: one
HEAD request per tile, with no payload bytes fetched.

## Homogeneity

The recipe uses one producer, one processing chain, one season, one
polarization, one temporal baseline and one quantization
(DN = round(gamma x 100)). It never mixes in other seasons, HH,
COH06/18/24/36/48 (different decorrelation regimes), AMP backscatter (uint16),
the rho/tau/rmse decay-model parameters (uint16), or the inc/lsmap auxiliary
layers. COH12 was chosen because it exists for every tile in the block.
COH06 is absent here (the N40W105 listing has only COH12/24/36/48), presumably
because Sentinel-1 only had a 12-day repeat over this region in 2020.

## Conversion

1. `download.sh` fetches each pinned object with resumable curl into `.part`.
   It checks exact size and MD5, then checks the GeoTIFF layout with
   `scripts/s1coh.py check-header`: classic little-endian TIFF, 1200 x 1200,
   BitsPerSample 8, SampleFormat 1, Compression 5 (LZW), Predictor 1, 200
   strips of 6 rows, GDAL_NODATA "0", 3-arcsec pixel scale, a tiepoint equal to
   the tile's upper-left corner, and a first strip that decodes to valid DNs.
   Only then is the file renamed into place.
2. `build.sh` runs a decoder self-test first: synthetic LZW streams covering
   KwKwK, clear codes, 12-bit codes and truncation rejection, plus a synthetic
   strip GeoTIFF. It then decodes every strip with a buffered pure-Python
   TIFF-LZW decoder (MSB-first, 256 = clear, 257 = EOI, early change). Each
   strip must decode to exactly 7,200 bytes ending in EOI. The strips are
   concatenated in order. The DNs are written unchanged to
   `samples/<id>/summer_vv_coh12_u8/<TILE>.bin`, and the index is written to
   `index/<id>/samples.jsonl`.
3. `verify.sh` re-decodes every source tile and compares the result
   byte-for-byte with the emitted sample. It also re-checks hashes, index
   fields, manifest totals and the nodata/degeneracy policy.

During authoring, the decoder output for two real tiles (N40W105 and N40W114)
matched an independent bit-serial TIFF-LZW implementation byte-for-byte: DN
ranges 1..100 and 1..97, no nodata. Decoding takes about 0.3 s per tile.

## Realized output (build 2026-10-05)

- Build and verify both pass: 150 samples, 216,000,000 bytes, median sample
  1,440,000 values. The aggregate SHA-256 of the per-sample SHA-256s is
  `a4903510d0d9933dab2ca2e859f7afb67cd64017d0906e8b45f289483a230828`.
- DN 0 (nodata) makes up 0.14% of all pixels and appears in 33 tiles. The
  largest gaps are in N37W102 (12.3%) and N38W102 (7.8%), where coverage is
  partial; every other tile is below 0.5%.
- DN range is 1..100 with 90–100 distinct DNs per tile. Global quantiles:
  1% = 4, 25% = 30, median = 48, 75% = 66, 99% = 88.
- Per-tile mean DN runs from 15.6 (N45W100, eastern-plains cropland) to 80.5
  (N40W114, Great Basin desert).
- One tile compresses only 1.5–1.8x with zlib-9/xz: speckle-like,
  high-entropy material.

## Missing values

DN 0 is the producer's nodata value and stays in place. A tile fails the
recipe if it is all nodata, more than 50% nodata (not expected for an
interior block), has fewer than 3 distinct DNs, contains a DN above 100, or
duplicates another raster.

## License and attribution

The bucket documentation (`index.html`, "License and Citation") says: *"The use
of these data fall under the terms and conditions of the Creative Commons
Attribution 4.0 International Public License. Contains modified Copernicus
Sentinel data."* The Google Earth Engine catalog entry for the same data set
also lists CC-BY-4.0. Cite:

> Kellndorfer, J., Cartus, O., Lavalle, M. et al. Global seasonal Sentinel-1
> interferometric coherence and backscatter data set. *Sci Data* 9, 73 (2022).
> doi:10.1038/s41597-022-01189-6. Contains modified Copernicus Sentinel data.

## Caveats

- This is a processed geophysical product (a seasonal median quantized to
  0.01), stored natively by the producer as uint8. It is not a local remap.
- Values use only 0..100, roughly 7 bits of the 8-bit width.
- Nearest families: `sentinel1_grd_measurement_u16` (GRD amplitude DN, a
  different product and quantity) and the downstream EHT radio-interferometer
  visibilities (unrelated). No InSAR coherence material exists locally or
  downstream.

## Commands

```bash
bash staging/earthbigdata_s1_global_coherence_vv_coh12_u8/download.sh
bash staging/earthbigdata_s1_global_coherence_vv_coh12_u8/build.sh
bash staging/earthbigdata_s1_global_coherence_vv_coh12_u8/verify.sh
```
