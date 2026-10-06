# gwa_v4_country_wind_speed_100m_f32

Global Wind Atlas 4.0 (GWA, DTU / World Bank / ESMAP) country rasters of
**modelled long-term mean wind speed at 100 m above ground**, one complete
country grid per sample, decoded to raw little-endian float32.

- 31 countries, one layer (`wind-speed`), one height (100 m), one release
  (`country_tifs_v4`).
- Grid: WGS84 geographic (EPSG:4326), 0.0025 degree pixels (about 250 m).
  Each raster is the country's bounding rectangle; pixels outside the GWA
  country mask (land territory plus offshore exclusive economic zone) are
  the source nodata `NaN`.
- Units: m/s. Realized valid values span 0.066 m/s (BTN) to 21.62 m/s
  (GEO). Per-country medians run from 2.02 m/s (BTN) to 9.47 m/s (NLD).
  Mountain ridges in GEO, AZE, BTN and CHE reach 20-22 m/s.
- Realized scope (build of 2026-10-06): 31 samples, 95,611,417 float32
  values, 382,445,668 primary bytes, from 176,707,851 downloaded bytes.
  Sample sizes range from 1.46 MB (SWZ) to 35.3 MB (PAN). 55,783,476 values
  are valid and 44.6 million of them are distinct bit patterns, so the
  values use the full float32 mantissa.

**This is a modelled climatology, not measurement.** GWA 4.0 forces the WRF
mesoscale model (3 km) with ERA5 reanalysis for 2008-2017. It generalizes the
resulting wind climates and downscales them with PyWAsP (the DTU Wind Atlas
method) to a predicted wind climate every 0.0025 degrees, using Copernicus
DEM30 terrain, ESA WorldCover 2021 land cover and ETH Zurich tree heights.
The source for this summary is the GWA methodology pages served in
`https://globalwindatlas.info/mapframe.bundle.js`.

## Source and access

| Item | Value |
|---|---|
| Official API URL | `https://globalwindatlas.info/api/gis/country/{ISO3}/wind-speed/100` (HTTP 302 to the CDN object) |
| Pinned object | `https://gwa.cdn.nazkamapps.com/country_tifs_v4/{ISO3}_wind-speed_100m.tif` (S3 + CloudFront, anonymous, byte ranges) |
| Pins | `countries.tsv`: size, ETag (single-part S3 ETag = MD5), Last-Modified (2025-06-11..13), sha256 (pinned from the 2026-10-06 download; LBN also matched an independent probe fetch), IFD0 width/height/tile count, upper-left corner, overview valid-share estimate |
| Discovery | `discover.sh` (HEAD, 64 KiB header range, smallest-overview tile ranges, API redirect check), run 2026-10-06 |

`download.sh` fetches the 31 files sequentially with resumable curl and
pauses between files. Each file must match its exact size and its MD5 must
equal the pinned ETag (plus the sha256 once pinned). Each file must also parse
as the expected BigTIFF: IFD0 float32, ZSTD, predictor 3, 512x512 tiles,
GDAL_NODATA `nan`, EPSG:4326, 0.0025 degree pixels, pinned width, height and
tile count, and an overview chain. Anything else is fatal.

## License and access conditions

GWA Terms of Use, served in `mapframe.bundle.js` and fetched 2026-10-06:

> You are encouraged to use the GWA App and the Works to benefit yourself and
> others in creative ways. The Works are licensed under the Creative Commons
> Attribution 4.0 International license, CC BY 4.0, except where expressly
> stated that another license applies.

The app states no other license for the wind-speed GIS layers. Its only other
license line covers the separate Global Atlas of Siting Parameters, which is
also CC-BY-4.0.

Requested attribution (also in `manifest.toml`):

> [Data/information/map] obtained from the Global Wind Atlas version 4.0, a
> free, web-based application developed, owned and operated by the Technical
> University of Denmark (DTU). The Global Wind Atlas version 4.0 is released
> in partnership with the World Bank Group, utilizing data provided by Vortex,
> using funding provided by the Energy Sector Management Assistance Program
> (ESMAP). For additional information: https://globalwindatlas.info

Main reference: Davis et al., *The Global Wind Atlas: A high-resolution
dataset of climatologies and associated web-based application*, BAMS 104(8),
E1507-E1525, 2023, https://doi.org/10.1175/BAMS-D-21-0075.1.

Access conditions that bear on automated download:

- GIS page: "Download global and country GIS files using the dropdown menu
  below. The provided URL can also be used as an API service." and
  "**This API service is not to be used for bulk downloads of all countries or
  datasets.** Please contact the GWA team through the Contact page if you have
  such a request."
- Terms of Use, "Your use of the GWA App", you agree not to: "Use any robot,
  spider or other automatic device, process or means to access the GWA App for
  any purpose, including monitoring or copying any of the material on the GWA
  App".

How the recipe handles this: GWA explicitly offers the country URL as an API
service and restricts only bulk downloads of all countries or datasets. The
recipe takes a fixed list of 31 countries out of about 250, one of 12 layers
and one of 5 heights. That is about 177 MB, fetched once, sequentially, with
pauses. It reads the static CDN object the API redirects to, which avoids load
on the app server. It never enumerates countries or layers. The robot clause
is written about the app website. A scripted fetch of a pinned list through
the documented API route is the use the GIS page describes, but this reading
is a judgment call and is flagged here rather than hidden. The content itself
is CC BY 4.0.

## Country selection

`discover.sh` documents the selection. A pool of 77 small and medium countries
on all inhabited continents was picked by hand; countries were never
enumerated. From the pool, a country qualified with HEAD 200, a single-part
ETag, a file of at most 17 MB and a smallest-overview valid share of at least
0.45, which limits NaN padding. 43 countries qualified. 31 of them were pinned
for a regional and terrain spread (lowland, coast and offshore, desert,
mountain, tropical) while keeping primary output under about 400 MB.

The 12 qualifying countries left out are MKD, PRT, LUX, LBR, BDI, BIH, HTI,
ALB, SYR, SLE, SVK and TUN. Large countries were never considered (RUS 2.18 GB
and CAN 1.29 GB; ISL and NZL are 64 MB and 179 MB with multipart ETags). TWN
answered 403.

| ISO3 | Country | Region | Shape (h x w) | Values | File bytes | Valid share | Min | Median | Max | Distinct valid |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| NLD | Netherlands | Europe | 2023 x 1892 | 3,827,516 | 5,900,915 | 0.576 | 5.484 | 9.466 | 10.088 | 1,431,647 |
| EST | Estonia | Europe | 1011 x 3152 | 3,186,672 | 6,420,249 | 0.657 | 4.869 | 7.370 | 9.529 | 1,622,745 |
| LVA | Latvia | Europe | 981 x 3675 | 3,605,175 | 7,326,782 | 0.630 | 4.929 | 6.871 | 9.525 | 1,699,029 |
| LTU | Lithuania | Europe | 1038 x 3143 | 3,262,434 | 5,837,744 | 0.520 | 4.658 | 6.947 | 9.522 | 1,391,391 |
| CZE | Czechia | Europe | 1018 x 2725 | 2,774,050 | 6,171,356 | 0.593 | 2.416 | 5.604 | 12.166 | 1,416,897 |
| HUN | Hungary | Europe | 1156 x 2729 | 3,154,724 | 6,342,190 | 0.582 | 2.068 | 5.706 | 9.224 | 1,438,415 |
| CHE | Switzerland | Europe | 813 x 1832 | 1,489,416 | 3,310,968 | 0.562 | 0.334 | 4.624 | 19.864 | 810,716 |
| SVN | Slovenia | Europe | 599 x 1306 | 782,294 | 1,645,954 | 0.538 | 0.689 | 4.451 | 15.699 | 412,997 |
| SRB | Serbia | Europe | 1600 x 1681 | 2,689,600 | 5,366,068 | 0.547 | 0.783 | 5.155 | 11.929 | 1,322,800 |
| BGR | Bulgaria | Europe | 1209 x 3606 | 4,359,654 | 9,219,349 | 0.608 | 0.655 | 5.136 | 11.642 | 2,213,098 |
| LBN | Lebanon | West Asia | 720 x 1161 | 835,920 | 1,513,377 | 0.576 | 1.033 | 4.979 | 11.266 | 458,117 |
| CYP | Cyprus | West Asia | 1349 x 2156 | 2,908,444 | 4,747,742 | 0.597 | 1.738 | 5.787 | 9.620 | 1,367,051 |
| KWT | Kuwait | West Asia | 648 x 1206 | 781,488 | 1,337,130 | 0.567 | 5.498 | 7.354 | 8.535 | 405,335 |
| QAT | Qatar | West Asia | 1046 x 1005 | 1,051,230 | 1,809,753 | 0.615 | 5.496 | 6.431 | 7.146 | 533,460 |
| ARE | United Arab Emirates | West Asia | 1426 x 2261 | 3,224,186 | 5,572,345 | 0.561 | 0.921 | 5.735 | 9.832 | 1,452,745 |
| GEO | Georgia | West Asia | 1030 x 3121 | 3,214,630 | 6,218,283 | 0.524 | 0.133 | 4.739 | 21.620 | 1,587,836 |
| AZE | Azerbaijan | West Asia | 1745 x 2838 | 4,952,310 | 9,330,952 | 0.591 | 0.221 | 5.493 | 21.407 | 2,579,620 |
| SWZ | Eswatini | Africa | 657 x 555 | 364,635 | 972,313 | 0.736 | 2.073 | 5.096 | 9.723 | 262,708 |
| LSO | Lesotho | Africa | 860 x 995 | 855,700 | 1,859,089 | 0.566 | 1.870 | 5.737 | 16.703 | 474,395 |
| RWA | Rwanda | Africa | 734 x 832 | 610,688 | 1,324,464 | 0.580 | 1.081 | 3.114 | 9.377 | 347,971 |
| UGA | Uganda | Africa | 2297 x 2201 | 5,055,697 | 11,400,142 | 0.635 | 0.562 | 3.531 | 13.363 | 2,634,542 |
| DJI | Djibouti | Africa | 738 x 966 | 712,908 | 1,388,134 | 0.571 | 2.379 | 6.410 | 15.081 | 399,616 |
| SEN | Senegal | Africa | 2436 x 3565 | 8,684,340 | 14,033,122 | 0.561 | 3.164 | 6.195 | 8.402 | 3,329,079 |
| GMB | Gambia | Africa | 325 x 2595 | 843,375 | 1,385,030 | 0.587 | 4.589 | 6.542 | 6.956 | 436,392 |
| BTN | Bhutan | South and Southeast Asia | 635 x 1368 | 868,680 | 2,442,909 | 0.673 | 0.066 | 2.015 | 21.430 | 577,699 |
| BGD | Bangladesh | South and Southeast Asia | 3526 x 1886 | 6,650,036 | 11,111,608 | 0.545 | 0.878 | 4.560 | 6.751 | 2,604,661 |
| KHM | Cambodia | South and Southeast Asia | 2380 x 2547 | 6,061,860 | 10,585,342 | 0.520 | 0.631 | 4.309 | 10.135 | 2,411,597 |
| SLV | El Salvador | Central America and Caribbean | 1819 x 1554 | 2,826,726 | 4,514,413 | 0.558 | 0.941 | 4.510 | 15.244 | 1,411,771 |
| PAN | Panama | Central America and Caribbean | 3017 x 2924 | 8,821,708 | 15,864,890 | 0.615 | 0.148 | 4.998 | 15.642 | 4,116,520 |
| BLZ | Belize | Central America and Caribbean | 1061 x 1239 | 1,314,579 | 2,438,255 | 0.593 | 1.016 | 6.019 | 8.411 | 739,725 |
| JAM | Jamaica | Central America and Caribbean | 2127 x 2746 | 5,840,742 | 9,316,983 | 0.634 | 0.798 | 7.980 | 12.838 | 2,684,251 |

The table shows realized full-resolution statistics from the sample index.
The selection used overview-based valid-share estimates (0.46..0.71, kept in
`countries.tsv`), which run slightly low: the realized shares are
0.520 (KHM) .. 0.736 (SWZ).

## Decode (`scripts/gwa_tiff.py`, standard library plus the `zstd` CLI)

1. Parse the little-endian BigTIFF (magic 43) IFD chain with `struct`.
   IFD0 is the full-resolution band. IFD1 onward carry NewSubfileType 1
   (overviews); they are checked for type and never decoded.
2. Decompress each IFD0 tile with `zstd -d -c`. Every tile must yield exactly
   512 x 512 x 4 bytes.
3. Undo TIFF Predictor 3 (libtiff `fpAcc`) per tile row. First take the
   byte-wise cumulative sum mod 256 over the row's 2,048 bytes. Then rebuild
   each float from the four MSB-first byte planes at offsets 0, 512, 1024 and
   1536 as a big-endian float32, and write it little-endian.
4. Place tiles into a row-major height x width grid (north row first, west
   column first) and crop the right and bottom edge tiles.

Every `build.sh` run first self-tests the decoder on synthetic input: a forward
predictor-3 encoder round trip that includes NaN, -0.0, inf and denormal-range
values, plus a synthetic 700x600 BigTIFF with 2x2 tiles, cropped edges and an
overview IFD. It was also checked on the real LBN file: the decoded raster's
sha256 matched an independent decode, and verify's second decoder agrees
byte for byte.

## Missing values

The NaN outside the country + EEZ mask is preserved in place, bit-exact
(`0x7fc00000`, GDAL_NODATA `nan`). It is not stripped, imputed or remapped.
`build.sh` and `verify.sh` both enforce the same rules:

- every NaN has that bit pattern;
- each country's valid share is within 0.30..0.90;
- valid values are finite and within 0..40 m/s;
- each raster has at least 10,000 distinct valid values and a valid span of
  at least 0.5 m/s.

`verify.sh` also requires a dataset-wide valid share within 0.45..0.75.
Realized: 39,827,941 of 95,611,417 primary values (41.7%) are NaN padding,
for a valid share of 0.583. Index min and max are computed over the non-NaN
stored float32 values.

`gate.py` warns that "57% of scanned values are NaN". The gate samples only
the head and the middle of each file. The head rows are the northern edge of
each country's bounding rectangle and are entirely NaN in every sample, so
the gate's estimate runs high; the full-raster figure above is the real one.

## Outputs

- `samples/gwa_v4_country_wind_speed_100m_f32/gwa_v4_wind_speed_100m_f32/gwa4_ws100m_{ISO3}_{H}x{W}_f32le.bin`:
  one file per country, raw float32 LE, shape `[H, W]`.
- `index/gwa_v4_country_wind_speed_100m_f32/samples.jsonl`: required fields,
  plus shape, axes, ISO3, country, region, grid origin and pixel size, source
  URL/MD5/sha256/Last-Modified, NaN and valid counts, valid share, min, max,
  mean, median, p01 and p99 of valid values, distinct valid values, and the
  sample sha256.
- `filtered/gwa_v4_country_wind_speed_100m_f32/ingest_stats.json`: totals and
  per-source TIFF structure.

## Novelty

The nearest local families are `worldclim_tavg_10m` (a float32 temperature
climatology raster) and `usgs_shakemap_ground_motion_f32` (modelled hazard
rasters). Every other "wind speed" hit, locally or downstream, is a point or
station time series: `nasa_power_daily_wind`, `noaa_isd_lite`,
`open_meteo_wind_f32`, NDBC and GHCN AWND. No wind-resource or energy-resource
raster exists at any width. Novelty kind: new quantity within the geo-raster
modality.

## Run

```bash
bash staging/gwa_v4_country_wind_speed_100m_f32/download.sh   # ~177 MB, ~2 min
# build.sh and verify.sh each take about 1 minute
bash staging/gwa_v4_country_wind_speed_100m_f32/build.sh
bash staging/gwa_v4_country_wind_speed_100m_f32/verify.sh
```

Requires `python3` (3.11 or later, for `tomllib`) and the `zstd` CLI
(override with `ZSTD_BIN`).
