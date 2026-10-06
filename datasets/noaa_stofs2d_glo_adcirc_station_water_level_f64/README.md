# NOAA STOFS-2D-Global v2.1 (ADCIRC) station water-surface elevation, float64

One primary series, `stofs2d_glo_fcst61_zeta_f64`: the complete `zeta`
variable of NOAA's operational STOFS-2D-Global ADCIRC station output file
(`stofs_2d_glo_fcst.61.nc`, ADCIRC "fort.61") for 40 00z forecast cycles.
Each sample is one cycle's full matrix of 1260 six-minute time steps x 1688
fixed output stations of native IEEE float64 water-surface elevation (m above
the geoid), written byte-exactly in the file's own time-major order.

| | |
|---|---|
| Source | NOAA NODD bucket `noaa-gestofs-pds` (AWS Registry of Open Data: `noaa-gestofs`) |
| Objects | `stofs_2d_glo.YYYYMMDD/00/rerun/stofs_2d_glo_fcst.61.nc`, 00z, 2024-06-01 + 20k days, k = 0..39 (last 2026-07-21) |
| Download | 40 files, 632,438,615 bytes (plus 40 ~1 KB listings) |
| Samples | 40 x (1260 x 1688) float64 = 40 x 17,015,040 bytes = 680,601,600 bytes, 85,075,200 values |
| Model | ADCIRC, STOFS-2D-Global v2.1 (`version = noaa.stofs.2d.glo.v2.1.0r1.v55.12`, OceanMesh2D grid) |

## License

AWS Registry of Open Data, `datasets/noaa-gestofs.yaml`, License field:

> NOAA data disseminated through NODD are open to the public and can be used
> as desired. NOAA makes data openly available to ensure maximum use of our
> data, and to spur and encourage exploration and innovation throughout the
> industry. NOAA requests attribution for the use or dissemination of
> unaltered NOAA data. However, it is not permissible to state or imply
> endorsement by or affiliation with NOAA. If you modify NOAA data, you may
> not state or imply that it is original, unaltered NOAA data.

Citation: Office of Coast Survey; National Centers for Environmental
Prediction (2020). NOAA Global Surge and Tide Operational Forecast System 2-D
(STOFS-2D-Global). https://doi.org/10.25923/ng4h-4b85

## What the material is

STOFS-2D-Global runs ADCIRC on a 12.8 M-node global unstructured mesh four
times a day, forced by GFS winds, pressure and sea ice. Each run writes the
simulated water level at a fixed list of output stations: coastal tide
gauges and NWS forecast/verification points worldwide. The values are
full-mantissa doubles (e.g. `2.545790017430244`), not decimal-rounded.

Realized value ranges over the 40 cycles:

- 1,687 stations stay within -10.73..+8.23 m. Per-cycle maxima are 4.2-8.2 m;
  per-station medians in the first cycle are about -0.5..3.7 m.
- **Station index 1649 is an artifact.** Its label is `UJ816 SOUS00 SA816`,
  at 35.44E 46.22N on the Sea of Azov coast. It carries 45.9..219.8 m in every
  cycle, as a smooth series with a median of about 112 m. That is physically
  impossible for a sea-level coast, so it is a model artifact at that node,
  not a real water level. The scout card's "inland stations reach ~118 m" came
  from this single station. The recipe keeps it unchanged because it is the
  published model output, and editing or dropping one column would be a local
  remap. It does dominate each sample's max.
- Station index 516 (`UH731 ... GL191 Puerto Madryn`) has the lowest values,
  down to -10.73 m in some cycles: short drying-edge excursions.

In every pinned file the time axis is exactly `cycle - 21600 s + 360 s * (i + 1)`
for i = 0..1259, i.e. cycle - 5.9 h to cycle + 120 h. The `rundes` attribute
says "-6 hr nowcast and +180 hr forecast", but this native file stops at
+120 h. The recipe checks the actual lattice, not the attribute text.

## Scope and homogeneity

- Window probe (S3 listings for the 1st/11th/21st of every month, plus header
  range reads). Files up to at least 2024-05-11 are the older product: title
  `STOFS_2D_GLOBAL.V1.1.0`, 1,687 stations, 960 steps, ~12.1 MB. From
  2024-05-21 through 2026-08-11 every probed file is v2.1 with 1,688 stations
  and 1,260 steps, ~15.8 MB. From 2026-08-21 the cycle folders hold STOFS v3.1
  `surf/tide` products and no `fcst.61`. The bucket README dates v3.1 from the
  2026-08-17 12z cycle.
- All 40 pinned files were header-probed. Each has the identical version,
  runid, `_NCProperties`, time base (`seconds since 2024-04-04 12:00:00`),
  zeta layout and filters, and byte-identical station coordinates.
- One station label changed between the 2025-02-16 and 2025-03-08 pinned
  cycles: index 68, NOAA 8725110, "Naples, Gulf of Mexico" became "Naples, Gulf
  Coast". Coordinates did not change. Both station_name hashes are pinned with
  that switch date.
- Only 00z cycles, 20 days apart, are used, so the 126 h windows never
  overlap. Twenty days is not a multiple of the 14.8-day spring-neap cycle, so
  tidal phase varies across samples, and the 40 cycles span two years of
  seasons and storm conditions.
- Why 40: the source has about 3,200 cycles in the window, but each matrix is
  17 MB. Forty cycles (680 MB) is a bounded subset under the 1 GB cap and well
  above the ~100 MB downstream selection size. The cycles are evenly spread
  rather than consecutive.

## Decode

NetCDF4/HDF5, decoded with `scripts/h5lite.py`, a pure-stdlib reader copied
verbatim from the accepted `noaa_cdr_seaice_conc_nh_daily_u8` recipe. Layout
details:

- superblock v0, version-2 object headers (lookup3 checksums verified), and
  compact root links
- `zeta` is float64 LE with shape (1260, 1688), chunked (1, 1688), filter
  pipeline exactly `[shuffle(element size 8), deflate(level 2)]`, and a
  version-1 chunk B-tree (one depth-1 root over 22 leaves in the files probed)

Each chunk is zlib-inflated to exactly 13,504 bytes and byte-unshuffled (byte
j of element k is stored at `j*1688 + k`). The rows are then concatenated in
time order. No value is modified.

`verify.sh` re-derives each sample along a different route from build:

- **Chunk list.** Build gets it by recursive B-tree descent. Verify walks the
  leaf level via right-sibling pointers and checks the left-sibling back
  pointers.
- **Byte check.** Verify re-shuffles each stored time step and compares it
  byte-for-byte with the inflated source chunk.
- **Statistics.** It recomputes the statistics from the sample files.

`scripts/selftest_stofs.py` runs before check-downloads, build and verify.
It builds STOFS-shaped synthetic HDF5 files from scratch: superblock v0,
compact links, an OCHK continuation, a two-level chunk B-tree, shuffle+deflate
chunks, a chunked time axis and contiguous coordinates. It checks exact
round-trip through both routes, plus rejection of:

- wrong cycle date
- other filters or shuffle widths
- missing chunks, a set filter mask, truncated chunks
- a broken sibling chain
- moved or renamed stations
- a shifted time axis, an extra link, another model version
- header corruption
- NaN, Inf, out-of-range, all-fill and constant matrices

The decoder's metadata checks were also run on real 2024-06-01 and 2026-07-21
files through HTTP range requests, and real chunks were decoded to plausible
full-precision values.

## Missing values

ADCIRC writes `-99999.0` (the variable `_FillValue` and global `dry_Value`)
for stations whose mesh node is dry at an output step. These native sentinels
stay in place. Each index row records `fill_count`, `stations_with_fill` and
`always_fill_stations`. `min`/`max`/`mean` are computed over non-fill values
only.

Realized fill: 132,410 values, 0.156% of 85,075,200. Each cycle has 6-33
stations with any fill. One station, index 119 (`FRDP4 ... 9753216 PR
Fajardo`), is fill at every step of every cycle; it stays as an all-fill
column.

Every non-fill value must be finite and inside (-100, 500) m. Nothing is
clipped; any value outside that range is fatal. The realized extremes are
-10.73 m and +219.80 m (station 1649, above). Build and verify apply the
identical policy.

## Validation chain

1. `download.sh` fetches one ListObjectsV2 response per object. Key, size and
   ETag must equal `sources.tsv`, which is pinned by SHA-256 in
   `scripts/stofs61.py` and must follow the 00z/20-day lattice.
2. Resumable curl (`-C -`, `--speed-limit 1024 --speed-time 120`, no
   `--max-time`) writes into `.part` files. A file is promoted only when its
   size matches and its locally recomputed multipart ETag matches. The ETag is
   the MD5 of the 8 MiB part MD5s. The part size follows from the bucket's
   1011-part fort.63 object, which pins it to [8,387,308; 8,395,611] bytes,
   i.e. 8 MiB. If a complete file fails this check, it is kept as
   `<name>.unverified` and the download stops with an error instead of
   re-fetching. Delete that file to force a fresh fetch.
3. `check-downloads` fully decodes and profiles every file before download
   succeeds.

## Novelty and nearest families

There are no STOFS/ADCIRC recipes, registry rows or downstream entries
(`tools/autocollect/novelty.py`). The nearest local 64-bit families are
`noaa_coops_water_level` and `noaa_tides_water_level`. Both are *observed*
CO-OPS gauge water levels: a few stations, decimal-quantized. This recipe is
the same physical quantity from a different generation process: an
unstructured-mesh hydrodynamic simulation emitting full-mantissa doubles over
a fixed global 1,688-station set. So this is a new source and process, not a
new modality.

## Alternatives considered and rejected

- `stofs_2d_glo.tCCz.points.cwl.nc` (date-folder root) is the documented
  public station product. It is classic NetCDF with 1860 steps (-5.9 h to
  +180 h), but post-processed: values are datum/anomaly-adjusted and
  decimal-rounded at mixed precision. In one record of 1688 values every
  non-fill value rounds exactly to at most 10 decimals, many to 5-6 (e.g.
  `2.72179` where fort.61 has `2.545790017430244`). That is a different,
  quantized regime, so it was not used.
- `prep.61` holds the nowcast-only run. 06/12/18z cycles overlap the 00z
  windows. fort.62/63/64/68 are velocity and full-mesh fields at 8-37 GB per
  file.

## Caveats

- The bucket README describes the `CC/rerun/` folders as holding the files of
  the system run "stored for NOAA internal reference"; no further
  documentation is given. The files are public in the NODD bucket under the
  same NODD terms. `fcst.61.nc` is the native ADCIRC station output of the
  forecast run.
- The bucket README says station output is referenced to local MSL. That
  describes the post-processed products. The native variable attribute says
  `water surface elevation above geoid`, and the recipe reports the attribute
  semantics.
- Station 1649 is an unphysical model node (45.9-219.8 m) and station 119 is
  permanently dry. Both are kept as published (see above).
- NOAA could delete or replace `rerun/` files. Any change to a pinned object
  makes `download.sh` fail rather than silently changing scope.

## Files

- `download.sh`, `build.sh`, `verify.sh` follow the repository script
  contract (`DATA_DIR`, logs in `$DATA_DIR/logs/<id>/`).
- `sources.tsv` pins the 40 objects (date, key, size, ETag). `discover.sh`
  documents how it was produced. The download does not run `discover.sh`.
- `scripts/stofs61.py` holds the listing check, planning, decode, build and
  verify. `scripts/h5lite.py` is the HDF5 reader. `scripts/selftest_stofs.py`
  is the synthetic self-test.

Outputs:

- `$DATA_DIR/samples/<id>/stofs2d_glo_fcst61_zeta_f64/stofs2d_glo_fcst61_zeta_<YYYYMMDD>_00z.bin`
- `$DATA_DIR/index/<id>/samples.jsonl`
- `$DATA_DIR/filtered/<id>/ingest_stats.json`
