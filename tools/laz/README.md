# tools/laz: pure-stdlib LAZ (LASzip) decoder

`laszip.py` decodes LASzip-compressed point clouds (`.laz`, including COPC)
into the uncompressed LAS point records they were made from, byte for byte.
It needs only the Python 3.12 standard library: no numpy, no laspy, laszip
or lazrs bindings. Recipes can use it to pull typed fields (X/Y/Z int32,
intensity u16, return and class bytes, GPS time f64, RGB/NIR u16, extra
bytes) out of LAZ tiles.

## Supported

| Area | Supported |
|---|---|
| LAS header | 1.0 to 1.4 (incl. the 1.4 64-bit point count), VLRs, EVLRs |
| LASzip VLR | user_id `laszip encoded`, record 22204: compressor, coder, version, options, chunk size, items |
| Compressor 1 (point-wise, one stream) | version 2 items |
| Compressor 2 (point-wise chunked) | POINT10 v2, GPSTIME11 v2, RGB12 v2, BYTE v2: point formats 0, 1, 2, 3 + extra bytes |
| Compressor 3 (layered chunked, LAS 1.4 native) | POINT14 v3, RGB14 v3, RGBNIR14 v3, BYTE14 v3: point formats 6, 7, 8 + extra bytes |
| Chunks | fixed size; variable size (chunk size `0xFFFFFFFF` or `0`, as in COPC) |
| Chunk table | compressed table (fixed: byte counts; variable: point and byte counts); table offset `-1` (offset read from the last 8 bytes of the file); missing or incomplete table (chunks decoded back to back, as LASzip does) |
| Input that is already uncompressed LAS | `decode_points` / `iter_chunks` return the raw records |

Rejected with a clear `LazError` (not silently mis-decoded):

* wave packet items, i.e. point formats 4, 5, 9, 10 (WAVEPACKET13/14);
* version 1 items (LASzip 1.x files from before 2012) and item version 4;
* coders other than 0 (arithmetic), unknown item types, item lists that do
  not cover the point record length.

Integrity checks: for point-wise chunks the arithmetic decoder must end
exactly at the chunk size given by the chunk table (LASzip performs the same
check); for layered chunks every layer decoder must consume exactly its
layer bytes. A desynchronised decoder therefore raises `LazError` instead of
returning wrong points.

## Usage

```python
import struct, sys
sys.path.insert(0, "tools/laz")
import laszip

hdr = laszip.read_header("tile.laz")          # dict: version, point_format, point_count,
                                               # point_record_length, scale, offset, min, max,
                                               # vlrs, evlrs, laszip (items, chunk size...)
hdr, records = laszip.decode_points("tile.laz")          # all records, LAS layout
hdr, head = laszip.decode_points("tile.laz", max_points=1000)

# progressive decoding, one LAZ chunk at a time (bounded memory)
rlen = hdr["point_record_length"]
for chunk_index, n, recs in laszip.iter_chunks("tile.laz"):
    for i in range(n):
        x, y, z, intensity = struct.unpack_from("<iiiH", recs, i * rlen)
```

For column extraction, whole-buffer operations are much faster than
per-point `unpack_from`:

```python
import array
returns = records[14::rlen]                     # one-byte field: strided slice
fmt = f"<iiiH{rlen - 14}x"                       # X, Y, Z, intensity, skip the rest
x, y, z, intensity = (array.array(t, col) for t, col in
                      zip("iiiH", zip(*struct.iter_unpack(fmt, records))))
```

Point record layouts are the standard LAS ones: formats 0-3 start with the
20-byte POINT10 core (X, Y, Z int32, intensity u16, return byte, class byte,
scan angle rank int8, user data, point source u16), then GPS time f64
(formats 1, 3), then RGB u16 x3 (formats 2, 3). Formats 6-8 start with the
30-byte POINT14 core (X, Y, Z, intensity, return byte, flags byte, class,
user data, scan angle int16, point source, GPS time f64), then RGB (7, 8),
then NIR (8). Extra bytes follow.

CLI:

```sh
python3 tools/laz/laszip.py info tile.laz            # header, VLRs, LASzip items, chunk table
python3 tools/laz/laszip.py decode tile.laz out.las  # uncompressed LAS (+ points/s on stdout)
python3 tools/laz/laszip.py decode tile.laz head.las --max-points 1000
```

`decode` writes a valid uncompressed LAS: the header with the compression
bits (0x80/0x40) of the point format cleared, offset to point data and VLR
count updated, all VLRs except the LASzip VLR, any padding before the point
data, the point records, then the EVLRs (with the LAS 1.4 EVLR start offset
updated). Other VLRs/EVLRs are copied verbatim; for COPC input that includes
the `copc` info VLR and hierarchy EVLR, whose offsets describe the
compressed file. With `--max-points` the point counts are reduced but the
bounds and per-return counts still describe the whole input.

## Validation

Fixtures are small public LAS/LAZ files from the laz-rs, PDAL, laspy, rlas,
copc.js and untwine repositories, pinned by commit URL, size and SHA-256 in
`fixtures.tsv` (29 files, 9.5 MB, largest 3.7 MB). They are not vendored:

```sh
bash tools/laz/fetch_fixtures.sh                    # -> ${DATA_DIR:-.data}/laz_fixtures/
python3 -m unittest tools/laz/test_laszip.py -v     # skips with a message if not fetched
```

Results on 2026-10-08 (Python 3.12.15): 39 tests, all passing, about 32 s.

Byte-exact against a reference LAS holding the same points: decoded records
identical, header point count and bounds equal, and the `decode` CLI output
byte-identical to the entire reference `.las` file (header, VLRs, EVLRs):

| LAZ fixture | Point format | Items (compressor) | Points |
|---|---|---|---|
| lazrs_point10.laz | 0 | POINT10 v2 (2) | 1,065 |
| lazrs_point-time.laz | 1 | POINT10, GPSTIME11 v2 (2) | 1,065 |
| lazrs_point-color.laz | 2 | POINT10, RGB12 v2 (2) | 1,065 |
| lazrs_point-time-color.laz | 3 | POINT10, GPSTIME11, RGB12 v2 (2) | 1,065 |
| lazrs_extra-bytes.laz | 3 + 27 extra | ... + BYTE v2 (2) | 1,065 |
| pdal_autzen_trim.laz | 3 | POINT10, GPSTIME11, RGB12 v2 (2), 3 chunks | 110,000 |
| rlas_extra_byte.laz | 1 + 4 extra | POINT10, GPSTIME11, BYTE v2 (2), LASzip 3.4.3 | 62 |
| laspy_extra.laz | 3 + 27 extra, LAS 1.4 header | ... + BYTE v2 (2), LASzip 3.1 | 1,065 |
| laspy_1_4_w_evlr.laz | 6, with EVLRs | POINT14 v3 (3) | 1,000 |

Field-by-field against a validated reference (no byte-identical LAS 1.4
format 7/8 reference pair was found in public test data, so these compare
the same points stored in another format or order):

| LAZ fixture | Checks | Reference |
|---|---|---|
| laspy_simple.copc.laz | format 7, POINT14 + RGB14 v3, 65 variable-size chunks of 6 to 24 points: multiset of all standard fields equal | laspy_simple.las (format 3) |
| copcjs_ellipsoid.copc.laz | format 7, variable chunks, 100,000 points: all fields equal | copcjs_ellipsoid.laz (format 3, decoded by the byte-exact v2 path) |
| copcjs_ellipsoid-1.4.laz | format 7 + 2 extra bytes, POINT14 + RGB14 + BYTE14 v3, 2 fixed chunks: every point matched; RGB = 257 x reference, intensity and the "InvertedIntensity" extra bytes are fixed one-to-one maps of the reference intensity, all other fields equal | copcjs_ellipsoid.laz |
| rlas_example.copc.laz | format 6, chunk size 0 (treated as variable, per spec and LASzip): all fields equal | rlas_example.las (format 1) |

Consistency only (no reference available): decoded point count, XYZ
extents (within half a scale step) and points-by-return histogram equal the
header, plus the per-layer consumption check:

| LAZ fixture | Point format | Items |
|---|---|---|
| untwine_eb.laz | 6 + 16 extra bytes | POINT14 + BYTE14 v3 |
| pdal_las_with_several_extra_byte_bloc.laz | 8 + 3 extra bytes, 697,721 points | POINT14 + RGBNIR14 + BYTE14 v3 |

For the format 8 file, additionally every decoded NIR value has a zero low
byte (8-bit source scaled by 256), which a desynchronised NIR layer would not
produce; this is plausibility evidence, not a byte-exact proof.

Synthetic variants built by the tests from the fixtures: chunk table offset
`-1` with the offset appended at the end of the file; chunk table offset
pointing to the data start (no table) for point-wise fixed, layered fixed and
layered variable chunks; a compressor 1 file derived from a single-chunk
compressor 2 file; partial decodes across chunk boundaries; the chunk
iterator; rejection of format 4 (wave packets), version 1 items and a
corrupted chunk.

Line coverage of `laszip.py` under the suite was measured with the stdlib
`trace` module. Decode paths that no fixture exercises, implemented from the
specification and the LASzip sources but not verified:

* scanner channel changes in POINT14 v3 (every fixture uses channel 0), and
  with them the context switches of RGB14 / RGBNIR14 / BYTE14 v3, including
  LASzip's documented quirk of predicting the first point after a switch to
  an already-used context from the previous context's last item;
* POINT14 v3 GPS time switching between its four time sequences (the
  GPSTIME11 v2 sequence switching is exercised);
* in GPSTIME11 v2, the reset of the reference difference after more than
  three extreme multipliers (500 and -10);
* NIR low-byte changes in RGBNIR14 v3 (the NIR high-byte path is
  exercised) and NIR values in general byte for byte;
* compressor 1 files written by a real compressor (only the derived variant
  above), and a layered chunk whose first layer is empty.

## Speed

Measured on 2026-10-08, CPython 3.12.15, one core of an AMD EPYC (Genoa)
server, `decode_points` on the fixtures (best of 3 runs; about +-7% run to
run):

| File | Format | Items | Chunks | Points | Seconds | Points/s |
|---|---|---|---|---|---|---|
| pdal_autzen_trim.laz | 3 | POINT10+GPSTIME11+RGB12 | 50000 | 110,000 | 1.45 | 75,700 |
| copcjs_ellipsoid.laz | 3 | POINT10+GPSTIME11+RGB12 | 50000 | 100,000 | 0.91 | 109,900 |
| copcjs_ellipsoid-1.4.laz | 7 | POINT14+RGB14+BYTE14 | 50000 | 100,000 | 1.48 | 67,500 |
| copcjs_ellipsoid.copc.laz | 7 | POINT14+RGB14 | variable | 100,000 | 1.58 | 63,100 |
| untwine_eb.laz | 6 | POINT14+BYTE14 (16 bytes) | 50000 | 9,310 | 0.18 | 51,500 |
| pdal_las_with_several_extra_byte_bloc.laz | 8 | POINT14+RGBNIR14+BYTE14 | 50000 | 697,721 | 12.33 | 56,600 |

So expect roughly 50,000 to 110,000 points per second, i.e. about 2 to 3
minutes per 10 million points; cost grows with the number of items and
extra bytes, and very small chunks (COPC nodes of a few dozen points) are
slower because models are re-created per chunk. Optimisations applied: the
symbol search uses `bisect_right` on the cumulative distribution (identical
result to LASzip's decoder table plus binary search, done in C), models are
created from cached initial states and only on first use, the bit-count
symbol decode is inlined in the integer decompressor (its hottest caller),
hot constants are literals, and records are packed with precompiled
`struct.Struct`s into a preallocated buffer per chunk. Together these gave
about +20% over the first correct version; further inlining was measured
and gave no gain beyond noise, so it was not kept.

## Implementation notes

* `ArithmeticDecoder`, `ArithmeticModel`, `ArithmeticBitModel`,
  `IntegerDecompressor` and `StreamingMedian5` follow the LAZ specification
  term for term (32-bit arithmetic is emulated with explicit masking where
  C relies on wrap-around, and C's truncating `/ 2` is reproduced).
* Item decoders: `Point10V2`, `GpsTime11V2`, `Rgb12V2`, `ByteV2` (one shared
  arithmetic stream per chunk) and `Point14V3`, `Rgb14V3`, `RgbNir14V3`,
  `Byte14V3` (one stream per layer, four scanner-channel contexts).
* Every chunk restarts all models and predictors, so `iter_chunks` decodes
  each chunk independently from its byte range in the chunk table.

## License and attribution

This module is an original Python implementation written for this
repository. It was written from:

* the LAZ specification published by rapidlasso GmbH, "LAZ Specification
  1.4 R1" (<https://downloads.rapidlasso.de/doc/LAZ_Specification_1.4_R1.pdf>);
* the LASzip reference implementation (C++, Martin Isenburg / rapidlasso
  GmbH, Apache License 2.0, <https://github.com/LASzip/LASzip>), consulted
  where the specification is terse (exact model sizes, context selection,
  chunk table and corrupt-chunk handling);
* laz-rs (Rust port of LASzip by Thomas Montaigu, Apache License 2.0,
  <https://github.com/laz-rs/laz-rs>), consulted for the same points.

No code was copied; the algorithms and numeric tables (return-number
context maps, model sizes, GPS multiplier constants) are those required by
the format. The test fixtures are downloaded from their upstream
repositories and not redistributed here: laz-rs (Apache-2.0), PDAL (BSD),
laspy (BSD-style), copc.js (MIT), rlas (GPL-3) and untwine (GPL-3); the
fixture files are used only as test inputs.
