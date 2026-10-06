# FMI Korpo weather radar, 0.5° PPI Doppler radial velocity (QC), uint8

Doppler **radial velocity** from the lowest (0.5°) plan-position-indicator
scan of the Finnish Meteorological Institute's Korpo (`fikor`) C-band radar on
the Archipelago Sea, after FMI quality control. FMI publishes every 5-minute
scan as a GeoTIFF in the public AWS bucket `fmi-opendata-radar-geotiff`. Each
file holds one 2003 x 2003 raster with 250 m pixels on the TM35FIN grid
(EPSG:3067), a 500 km square centred on the radar.

This recipe collects one product, `<timestamp>_fikor_ppi_0.5_vrad_qc.tif`.
The pixels are emitted unchanged as uint8 codes:

| code | meaning |
|---|---|
| 112..143 | radial velocity `v = 0.5 * code - 64` m/s, so -8.0 .. +7.5 m/s (GDAL_METADATA `SCALE 0.5`, `OFFSET -64`, `UNITS VRADH`) |
| 0 | inside coverage, no echo detected (inferred ODIM *undetect*) |
| 255 | GDAL NoData: outside the 250 km coverage disc (the square's corners, 21.6% of every raster) |

The radar folds (aliases) velocities into its single-PRF Nyquist interval of
about ±8 m/s. That is why only 32 velocity codes ever occur, and why fields
show sharp fold lines wherever the true wind exceeds about 8 m/s. The recipe
does **not** dealias.

## Scope

- 75 scans, one per sample: 2003 x 2003 uint8 = 4,012,009 values each,
  300,900,675 primary bytes in total.
- Download: 75 GeoTIFFs, 31,677,353 bytes (201–696 KB each).
- Scan times run from 2025-03-05 to 2026-03-19 at 00, 06, 12 or 18 UTC. There
  are six scans per calendar month, except February 2026, which has three
  because only six February days had enough echo and the two-day spacing rule
  removes three of them. The 13 months span all seasons (summer convection,
  autumn storms, winter snowfall; summer scans likely also contain clear-air
  echoes).
- The full population is on the order of 110,000 scans of this product in
  the Rack 10.7 window (288 per day). About 100 MB is enough for downstream
  selection, so the recipe takes a bounded, echo-rich, season-balanced subset.

### How the scans were chosen (`discover.sh`, metadata only)

1. HEAD all 1,584 candidates: every day from 2025-03-01 to 2026-03-31 at
   00/06/12/18 UTC. 1,554 exist; 30 return 404 (missing scans, e.g.
   2025-12-28 and 2026-01-03..07).
2. For each day, keep the largest of the four files. LZW file size tracks the
   echo area: about 37 KB for an echo-free scan, 200–700 KB for widespread
   echo.
3. For each month, rank those day-best scans by size, keeping only files of at
   least 200,000 bytes. Read a 4 KiB header range of each and run the same
   product check that `download.sh` uses, including the Software tag. Take the
   first six that pass, skipping any scan on the same or an adjacent day as an
   already chosen scan, so samples are at least two days apart.

`sources.tsv` pins each object's key, size, ETag (single-part MD5),
Last-Modified, S3 version id and Software tag. `download.sh` fetches by
version id.

## Homogeneity

The recipe uses one site, one elevation, one quantity, one QC flavour, one
code lattice (0.5 m/s steps, -64 m/s offset), one grid and one
processing-software version. The pinned window was chosen after finding that
the `ppi_0.5_vrad_qc` file name spans several processing eras:

| period | Software tag | notes |
|---|---|---|
| 2024-11-05..07 | – | lowest scan was 0.3°, not 0.5° (`ppi_0.3_vrad_qc`) |
| ≤ 2025-02 | `Rack_fmi.fi 8.3.2` | excluded |
| 2025-03 .. late 2026-03 | `Rack_fmi.fi 10.7` | **used** (last pinned scan 2026-03-19) |
| sporadic, e.g. 2025-10-28 18:00, 2025-11-24 06:00 | `Rack_fmi.fi 14.0.1` | excluded per file by the header check |
| by 2026-03-24 .. 2026-08 | `Rack_fmi.fi 16.4` | new description format `COMP:PPI(0.5)[0.5]:VRADH`; excluded |
| 2026-09 onward | – | renamed `ppi_0.5_vrad_finrad_qc.tif`, plus dual-PRF `qc2prf` variants; excluded |

Every file must carry exactly the pinned GDAL metadata (IMAGETYPE
`Weather Radar,fikor`, TITLE `PPI:`, UNITS `VRADH`, OFFSET `-64`,
SCALE `0.5`), GDAL_NODATA `255`, Software `Rack_fmi.fi 10.7`, description
`COMP:VRADH:PPI:elangles(0.5)`, and the pinned pixel scale and tiepoint.
Its pixels must lie in {0, 112..143, 255}. A code outside that set would mean
a different Nyquist interval or coding, and fails the recipe. The 0.7° and
1.5° VRAD products use the same 32-code interval but were left out to keep
one elevation.

## Conversion

1. `download.sh` runs the decoder self-test. It fetches each pinned object by
   version id with resumable curl into `.part`, then checks exact size and
   MD5. It then runs `scripts/fmivrad.py check-header` on the full file: the
   layout and metadata above, all 16 tiles decoding to exactly 512 x 512, and
   the same code-set, NoData-geometry and near-empty rules as the build. Only
   then is the file renamed into place.
2. `build.sh` runs the self-test, then decodes each scan. It parses the classic
   little-endian TIFF IFD and LZW-decodes the 16 tiles (MSB-first codes,
   Clear 256, EOI 257, early change, 9–12 bit). Tiles are placed row-major on
   a 2048 x 2048 canvas and cropped to 2003 x 2003, which drops GDAL's
   edge-tile padding. The codes are written unchanged to
   `samples/fmi_radar_ppi_vrad_u8/fikor_ppi_0p5_vrad_qc_u8/<YYYYMMDDHHMM>.bin`
   with an index row in `index/fmi_radar_ppi_vrad_u8/samples.jsonl`. Index
   extras include scan time, NoData/undetect/echo counts, velocity-code range,
   source key, version id, MD5 and SHA-256. Per-scan fractions go to
   `filtered/fmi_radar_ppi_vrad_u8/ingest_stats.json`.
3. `verify.sh` re-decodes every source scan, compares the result byte-for-byte
   with the emitted sample, and re-checks hashes, index fields, manifest
   totals, the missing-value policy, coverage of all 32 velocity codes and at
   least 12 calendar months.

The LZW decoder is adapted from the accepted
`earthbigdata_s1_global_coherence_vv_coh12_u8` recipe. During authoring it
matched an independent bit-serial TIFF-LZW implementation byte-for-byte on
the real scan 2025-06-15 12:00 (SHA-256 `2368bb56…`). A tamper test confirmed
that verify rejects a one-byte change.

## Missing values

Codes 255 (NoData, outside coverage) and 0 (no echo inside coverage) stay in
place as native codes. A scan fails if the 255 fraction is outside 0.20..0.30
(it is a fixed 865,338 pixels, 21.57%, in every probed scan). It also fails if
velocity codes cover less than 5% of the raster, if it has fewer than 16
distinct velocity codes, if any code lies outside {0, 112..143, 255}, if rows
are near-identical, or if it duplicates another raster.

## Authoring probes (2026-10-05)

| scan | file bytes | velocity pixels | undetect (0) | NoData (255) |
|---|---|---|---|---|
| 2025-06-15 12:00 | 361,114 | 21.9% | 56.6% | 21.6% |
| 2026-01-08 06:00 (2nd-smallest pick) | 203,414 | 11.7% | 66.8% | 21.6% |
| 2026-02-11 06:00 (smallest pick) | 201,246 | 12.9% | 65.5% | 21.6% |
| 2025-01-15 12:00 (dry, Rack 8.3.2, not used) | 39,458 | 0.25% | 78.2% | 21.6% |

All 32 velocity codes occur in each probed scan.

## Realized output (build 2026-10-05)

- The driver's download fetched 75 files, 31,677,353 bytes, all
  size/MD5/product-checked. Build and verify both pass: 75 samples,
  300,900,675 bytes, median sample 4,012,009 values, 13 calendar months.
  The aggregate SHA-256 of the per-sample SHA-256s is
  `f486e9c9651c77367460e6e5d37792b5525ccb0735dae3eb36fc220de7ed3dc3`.
  `gate.py` passes with no warnings.
- Over all pixels: velocity codes 32.7%, undetect (0) 45.7%, NoData (255)
  21.6%. NoData is exactly 865,338 pixels in every scan.
- Velocity coverage per scan runs from 11.7% (2026-01-08 06:00) to 60.8%
  (2025-10-30 18:00), median 31.6%.
- All 32 velocity codes occur in every scan. Across the series the velocity
  codes are close to uniform: 4.95 bits of entropy out of 5, and each code
  holds 0.6–3.7% of velocity pixels. The two outermost codes, 112 (-8.0 m/s)
  and 143 (+7.5 m/s), are the rarest. All-code entropy is 3.14 bits/pixel.
- Every 8th scan was compressed for comparison: 7.9–16.0x with zlib-9 and
  11.7–22.8x with xz. The source LZW GeoTIFFs are 9.5x smaller than the
  emitted rasters.

## License and attribution

FMI's [Radar data on AWS S3](https://en.ilmatieteenlaitos.fi/radar-data-on-aws-s3)
page says: *"The data is licensed by the Creative Commons Attribution 4.0
International license (CC BY 4.0)."* The AWS Open Data Registry entry
(`fmi-radar.yaml`) lists `License: Creative Commons Attribution 4.0
International (CC BY 4.0)`. Attribute the Finnish Meteorological Institute.

## Caveats

- This is an operational Cartesian resampling of polar gates, not raw gates.
  It is stored natively by FMI as uint8 codes.
- Only 34 of the 256 codes occur: 32 velocity codes plus two sentinels. The
  8-bit width is native, but the velocity payload carries about 5 bits.
- Sentinels (0 and 255) still cover 39–88% of each raster (67% overall),
  so the material compresses well.
- Selection by file size favours echo-rich scans. That is intended (dry scans
  are about 99% sentinels), but it biases toward widespread-echo weather.
- Code 0 is read as "no echo detected" from its spatial role and from lying
  outside the velocity interval. FMI's GeoTIFF metadata only declares 255.
- Nearest families: `noaa_nexrad_level3_nids_radials_u8` (NEXRAD Level-III
  N0Q base *reflectivity* radials) and `dwd_radolan_rw_precip_i16` (composite
  precipitation). No local or downstream family carries Doppler radial
  velocity.

## Commands

```bash
bash staging/fmi_radar_ppi_vrad_u8/download.sh
bash staging/fmi_radar_ppi_vrad_u8/build.sh
bash staging/fmi_radar_ppi_vrad_u8/verify.sh
```

`discover.sh` is documentation of how `sources.tsv` was resolved. It sends
about 1,600 HEAD requests plus header range reads, and writes
`sources.tsv.new` for review. The download, build and verify scripts never
run it.
