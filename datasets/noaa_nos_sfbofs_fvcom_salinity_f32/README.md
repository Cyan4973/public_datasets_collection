# NOAA NOS SFBOFS (FVCOM) nowcast 3-D salinity fields, native float32

One complete simulated salinity field per sample from NOAA's operational
**San Francisco Bay Operational Forecast System** (SFBOFS, FVCOM 4.4.7). Each
sample covers 20 terrain-following sigma layers × 54,120 nodes of the
unstructured triangular mesh. The mesh spans San Francisco Bay, the
Sacramento–San Joaquin Delta and the adjacent coastal ocean. Samples are the
salinity variable of the `t03z` cycle's nowcast hour-3 output
(`fields.n003`, valid 00:00 UTC), on 52 dates spaced 7 days apart through
2025 (2025-01-01 … 2025-12-24).

| | |
|---|---|
| Source | NOAA NODD bucket `noaa-nos-ofs-pds` (anonymous HTTPS, us-east-1) |
| Objects | `sfbofs/netcdf/YYYY/MM/DD/sfbofs.t03z.YYYYMMDD.fields.n003.nc`, 52 × 56,605,561 bytes, pinned by S3 ETag in `sources.tsv` |
| Fetched | 52 × 5,036,992 bytes = 261,923,584 bytes (byte ranges only, not the 2.94 GB of whole files) |
| Output | 52 samples × 4,329,600 bytes = 225,139,200 bytes; 56,284,800 float32 values |
| Sample | raw little-endian float32, row-major `(siglay=20, node=54120)`, layer 0 = surface (siglay −0.025) … layer 19 = bottom (−0.975) |
| License | NOAA NODD open data, U.S. Government work. Attribution is requested, and implying NOAA endorsement is not allowed (see manifest) |

## How it works

FVCOM writes each hourly fields file as NetCDF4/HDF5 (superblock v0,
version-2 object headers, dense link storage). `salinity` is
`float32 (time=1, siglay=20, node=54120)`, stored in four raw (unfiltered)
chunks of shape `(1, 10, 27060)`. `download.sh` therefore fetches only these
ranges of each object:

1. `head` = bytes `[0, 262144)`, holding every object header the decode needs
   (the deepest read is at about 80 KB)
2. 4 KiB windows at the salinity and time chunk B-tree nodes, at addresses
   parsed from the head
3. the contiguous `x`/`y` node coordinates, whose SHA-256 is pinned to prove
   every file uses the same mesh
4. the four salinity chunks (4 × 1,082,400 bytes) and the time chunk, at
   addresses parsed from the B-trees

Every range request carries `If-Match: "<pinned ETag>"`. Every response must
be HTTP 206 with the exact `Content-Range`, `Content-Length` and ETag. After
its ranges arrive, each file is fully decoded and validated before the next
file starts.

Validation covers the layout (link set, dtype, no filters, chunk grid,
filter masks), the mesh hash, the globals, the forcing file name for the date,
and `time` being the date at 00:00 UTC. It also checks the values: no fill
(9.96921e36), no NaN/Inf, everything inside (−1, 45), at least 100,000
distinct values, a modal value covering at most half the field, and not all
layers identical.

`build.sh` and `verify.sh` never trust stored offsets. They re-derive the
whole range plan by parsing `head.bin`, then the B-trees.
`scripts/fvcom_h5.py` is the accepted STOFS recipe's `h5lite.py` running over
a `Sparse` view: reading outside the fetched ranges raises an error, and
overlapping ranges must agree byte for byte. It checks the lookup3 checksum
of every object header, fractal-heap block and v2 B-tree node it reads.

Build copies each chunk into the output (chunk route). Verify re-decodes every
file through a different layer-walk route and compares the bytes. It also
recomputes stored-float32 statistics against the index and checks the manifest
totals. `scripts/selftest_sfbofs.py` runs first in both, on synthetic HDF5
files built from scratch (dense links via fractal heap and v2 B-tree, chunk
B-tree overlapping chunk 0). It covers the decode and its rejection paths.

## Scope and homogeneity

All samples share one model system, one mesh, one variable, one output type,
one cycle and one nowcast hour. Nothing else is mixed in: no temperature, no
forecast hours, no other OFS domains, no other cycles. Weekly spacing varies
the tide phase, river outflow and season. Realized values span 0.005 (fresh
Delta water) to 34.0143 (coastal ocean). Per-sample minima vary from 0.005
in the wet season to 8.56 in late December.

## Missing values

FVCOM's mesh has no land nodes, and `salinity` declares no `_FillValue`.
The HDF5 default fill is the netCDF float fill 9.96921e36. Any stored fill,
NaN/Inf or out-of-bounds value is fatal. Nothing is dropped or clipped. Dry
nodes keep their model value. None of the 52 samples has zeros. The modal value
is a freshwater floor (0.005, 0.05 or 0.1) or an ocean value, and covers at
most 1.36% of any sample. The index records the modal value and its
fraction, the zero count and the distinct count for each sample.

## Files

- `discover.sh`: how `sources.tsv` was resolved (one ListObjectsV2 call per
  exact key; not run by `download.sh`)
- `sources.tsv`: date, key, size, ETag for the 52 objects (SHA-256 pinned in
  the script)
- `scripts/sfbofs_salinity.py`: plan, response check, file check, build,
  verify
- `scripts/fvcom_h5.py`: sparse pure-stdlib HDF5 reader
- `scripts/selftest_sfbofs.py`: synthetic self-test
