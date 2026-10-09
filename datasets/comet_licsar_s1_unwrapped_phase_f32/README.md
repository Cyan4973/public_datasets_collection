# comet_licsar_s1_unwrapped_phase_f32

COMET LiCSAR Sentinel-1 geocoded **unwrapped interferometric phase**
(`<date1>_<date2>.geo.unw.tif`, radians, native IEEE-754 float32), one complete
raster per interferogram.

## Material

- Product: LiCSAR (COMET, GAMMA + SNAPHU) `geo.unw.tif`: unwrapped differential
  phase of a Sentinel-1 IW pair, topography removed, on a 0.001 deg WGS-84 grid.
  CEDA's description: "This is the unwrapped phase image in radian. The
  unwrapping is performed using SNAPHU. The zero values in the unwrapped file
  refer to the pixels which are masked out due to the low coherence."
- One regime: a single processor and product, single unit (rad), only
  consecutive 12-day pairs (Sentinel-1A only; summer 2023), only inland frames.
- Excluded: wrapped `diff_pha`, `diff_unfiltered_pha`, coherence `cc`,
  `mag_cc`, `bovldiff`/`sbovldiff` products, PNG previews, epoch products.

| frame | area | pass | raster (w x h) | pairs | source encoding |
|---|---|---|---|---|---|
| 001A_05031_131313 | central Spain | asc | 3498 x 2689 | 20230608 .. 20230819 (6) | zlib + predictor 3 |
| 043A_05221_121313 | eastern Anatolia | asc | 3364 x 2639 | 20230611 .. 20230822 (6) | uncompressed |
| 050D_05246_131313 | south-eastern Anatolia | desc | 3464 x 2870 | 20230612 .. 20230823 (6) | uncompressed |
| 094D_05100_131313 | central Anatolia | desc | 3414 x 2685 | 20230709 .. 20230919 (6) | uncompressed |

Exact files, sizes, Last-Modified values and SHA-256 are pinned in `sources.tsv`
(24 files, 776,518,900 bytes). Output: 24 samples, 224,351,928 float32 values,
897,407,712 bytes.

## How the selection was resolved (2026-10-08 probes)

- Frame listings: `LiCSAR_products/<track>/`; frame centre and mean height from
  `metadata/<frame>-poly.txt` and `metadata/metadata.txt`.
- Pairs: `interferograms/` listing filtered to 12-day pairs dated June to
  September 2023; the first six consecutive ones whose `geo.unw.tif` is
  present and strip-organised. In 094D_05100_131313 the pairs 20230615_20230627
  and 20230627_20230709 have no `geo.unw.tif`, so that run starts at 20230709.
- HEAD for size/Last-Modified; a 256 KB range GET for the TIFF IFD; 12 strip
  range GETs per file decoded to estimate the zero fraction (0.306 to 0.388;
  the realized full-raster values are 0.309 to 0.389, overall 0.336).
- Frames rejected during probing: 028A_05618 and 160A_05207 (no 2023
  `geo.unw.tif`), 116A_05167 (no pairs after 2022), 014A_05138 and 072A_05289
  (tiled TIFFs), 087A_05101 (tiled and strip files mixed in the window).
  The decoder deliberately rejects tiled layouts rather than supporting a
  second container path.

## Decoding

`scripts/licsar_unw.py` (pure stdlib) parses classic TIFF and BigTIFF, and
requires a single band, 32-bit, SampleFormat=3, PlanarConfiguration=1, strips
(tiled files are rejected), and Compression 1/8 with Predictor 1/3. For
predictor 3 (libtiff `fpAcc`) the decoder works row by row (RowsPerStrip may be
greater than 1): zlib inflate, a running byte sum mod 256 over width*4 bytes,
then the four MSB-first byte planes are de-interleaved into big-endian float32
and written little-endian. `selftest` round-trips synthetic TIFFs (classic and
BigTIFF; RowsPerStrip 1, 3, full and oversized; with and without zlib and
predictor; zeros, -0, tiny, huge and inf values) through both the build
decoder and the independent verify decoder. It also checks a known value and
confirms that a corrupted strip is rejected. On real data the two decoders
agreed byte-for-byte on probed predictor-3 strips.

## No-data policy

Zero is the upstream no-data value. Zeros come mostly from the corners of the
geocoded lat/lon bounding box that the tilted swath does not cover, plus
low-coherence masking. They are kept as `0.0` and never converted to NaN. The
index records the per-raster `zero_count`/`zero_fraction`. A raster is rejected
by download, build and verify alike if its zero fraction exceeds 0.5, if it
holds any non-finite value, if it is constant, or if fewer than 1000 distinct
values appear in a stride sample.

## License

The data are derived works of Copernicus Sentinel data, under the EU Legal
notice on the use of Copernicus Sentinel Data and Service Information. That
notice grants free reproduction, distribution, communication to the public,
and adaptation/modification, with attribution. The CEDA catalogue record for
"LiCSAR interferometry products" additionally states the Open Government
Licence v3.0. Verbatim quotes are in `manifest.toml` `[license].notes`.
Required acknowledgement:

> LiCSAR contains modified Copernicus Sentinel data 2023 analysed by the Centre
> for the Observation and Modelling of Earthquakes, Volcanoes and Tectonics
> (COMET). LiCSAR uses JASMIN, the UK's collaborative data analysis
> environment (http://jasmin.ac.uk)

Cite Lazecky et al. 2020 (doi:10.3390/rs12152430) and the CEDA record
(https://catalogue.ceda.ac.uk/uuid/52cda2e0e6c04272ae15ac836c1e8493).

## Run

```bash
bash staging/comet_licsar_s1_unwrapped_phase_f32/download.sh   # ~777 MB
bash staging/comet_licsar_s1_unwrapped_phase_f32/build.sh
bash staging/comet_licsar_s1_unwrapped_phase_f32/verify.sh
```
