# usgs_3dep_nc_geiger_laz_x_i32

Native LAS scaled int32 X record coordinates from USGS 3DEP Geiger-mode
airborne lidar: project `NC_Phase_4_CentralWestNC_GEIGER_A16`, Anson County
block (`NC_Phase4_Anson_2016`), Harris IntelliEarth Geiger-mode avalanche
photodiode (GmAPD) array sensor S/N003. The selected tiles were created on
2016-08-10 (LAS header creation date 2016/223, which the VPC `datetime`
copies), but by point GPS time they were acquired on 2016-03-16/17 (see
"Acquisition window" below).

## What is collected

- One sample per published LAZ tile (`USGS_LPC_NC_Phase_4_CentralWestNC_GEIGER_A16_<tile>.laz`,
  2,500 x 2,500 ft): the X field of every point record, in file order, as
  little-endian int32.
- X is the stored LAS integer: easting in NAD83(2011) North Carolina State
  Plane, in 0.01 US survey foot ticks, offset 0. Every tile is checked to have
  the same scale, offset, CRS, point format (6) and system identifier, so all
  samples sit on one tick lattice in one unit.
- Only X is emitted. Y and Z come from the same records and would not be a new
  family. Intensity, GPS time and the flag bytes are not emitted either.

Realized output (2026-10-08): 25 samples, 167,277,065 values, 669,108,260 bytes; median
7,614,983 values per sample (673,724 to 8,950,333).

## Acquisition window

`build.sh` reads the point GPS time (float64 at bytes 22-29 of every record)
alongside X and writes per-tile `gps_time_min`/`gps_time_max` and the overall
window to `filtered/<id>/build_stats.json`. GPS time is not emitted as a
series. The headers have `global_encoding = 17`; bit 0 marks adjusted standard
GPS time, and the build asserts it for every tile. So calendar time = GPS epoch
1980-01-06T00:00:00 + gps_time + 1e9 s.

Measured over all 167,277,065 points: 142,123,327.99994 to 142,211,440.00092
adjusted-standard seconds, i.e. 2016-03-16 00:28:47 to 2016-03-17 00:57:20 in
GPS calendar time. UTC is 17 s earlier (00:28:30 to 00:57:03), which in local
EDT is the evening of 15 March to the evening of 16 March 2016. Per-tile spans
run from 43 minutes to about 18 hours.

## Selection

`discover.sh` documents the resolution and `scripts/geiger_tiles.py select`
implements it:

1. Read the project VPC (a STAC FeatureCollection on the prd-tnm S3 bucket,
   2,533 tiles with `pc:count` and `datetime`).
2. Keep tiles whose VPC `datetime` is 2016-08-10 (1,785 tiles). That value
   copies the LAS header file-creation date (2016 day 223); it is not a flight
   date. The selection key is therefore the single LAS creation batch
   2016/223. download.sh, build.sh and verify.sh check that every selected
   tile carries the system identifier `IntelliEarthGmAPDSensorS/N003`. The
   other creation-date groups carry a mix of identifiers
   (`IntelliEarthGmAPDSensorS/N003`, `IntelliEarth GmAPD Sensor #003`,
   `IntelliEarth GmAPD Sensors #2&3`, sometimes mixed within one date). They
   are excluded to keep one processing batch, one identifier string and one
   acquisition window (2016-03-16/17 by GPS time).
3. Keep tiles with `pc:count` below 9,000,000 and sort by tile id. That gives
   25 tiles.

**Bias:** full interior tiles hold 17 to 31 million points (about 190 MB of
LAZ each), so a count cap is needed to stay under the 1 GB primary limit with
a reasonable number of samples. The cap favours partial tiles: tiles at
project or county edges and tiles with much open water. Judging by their
coordinates, the smallest ones (tiles 107435xx/107436xx) lie along the Pee Dee
River and Blewett Falls Lake on the county's eastern edge. This was inferred,
not checked against imagery. Within each tile the points are
complete and unaltered.

`download.sh` re-derives this selection from the live VPC and link list and
stops if it no longer matches `sources.tsv`.

## Scripts

- `download.sh`: fetches the VPC and link list (S3), then the 25 tiles from
  rockyweb.usgs.gov using `curl -C -` with `--retry 10 --retry-all-errors
  --speed-limit/--speed-time` (no `--max-time` on payloads) and an outer retry
  loop of 8 attempts. Each tile is validated before it is kept: exact size and
  ETag; LAS 1.4 header invariants (system id, software, creation date, format,
  record length, scale, offset, point count equal to `pc:count`, pinned
  header X bounds); the LASzip VLR; the chunk-table pointer; the CRS WKT EVLR;
  and the pinned sha256 where present. Digests go to
  `downloads/<id>/meta/sha256.tsv`. Re-runs skip valid tiles and resume
  partial `.part` files. About 1.235 GB in total.
- `build.sh`: re-validates the tiles, then decodes them in parallel (one
  process per tile) with the repository decoder `tools/laz/laszip.py`
  (`iter_chunks`). It copies bytes 0-3 of every 30-byte record into the
  sample, checks the point count and the X bounds, and writes
  `index/<id>/samples.jsonl` and `filtered/<id>/build_stats.json`.
- `verify.sh`: decodes every tile again, extracts X through a different
  path (`struct.iter_unpack('<i26x')`) and compares value by value. It
  re-checks the missing-value policy and the decoded extent against the header
  bounds (±2 ticks), rejects samples with fewer than 1,000 distinct values or
  a dominant value, and checks the index fields, sha256, min/max (from the
  stored int32) and the manifest totals.

Decode speed is about 74k points/s per process. Since tiles decode in
parallel, wall time is bounded by the largest tile (about 2 minutes).

## Missing values

LAS records have no missing X and there is no sentinel. All records are kept,
including any withheld, overlap or noise-classified points. A record-count
mismatch or an X outside the header bounds is fatal.

## License

USGS 3DEP data is U.S. Government public domain. The per-tile FGDC metadata
has `accconst` "None." and a `useconst` that asks for acknowledgement of the
originating agencies and a description of any modifications. Here the only
modification is extracting the X field byte for byte.

## Notes

- Within a tile the upper bytes of X are nearly constant (values of about
  1.6e8 to 1.74e8, spanning at most about 250,000 ticks). This is how the
  data is stored natively.
- The LAZ files are only on rockyweb.usgs.gov (prd-tnm S3 returns 404 for
  them). That host intermittently fails TLS handshakes (SSL_ERROR_ZERO_RETURN)
  and the egress proxy sometimes returns 503, hence the two retry levels.
- The `sha256` column of `sources.tsv` was filled from the first full
  download (2026-10-08) and is enforced on every re-run.
