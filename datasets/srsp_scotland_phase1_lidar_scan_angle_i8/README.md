# LiDAR for Scotland Phase I: per-point scan angle rank (int8)

One primary series, `srsp_phase1_scan_angle_rank_i8`. Each sample is the
complete LAS **Scan Angle Rank** field of one 1 km Phase I LAZ tile, stored as
raw signed int8 in the tile's point order. The field is the off-nadir angle of
the laser pulse in whole degrees. In stored order it sweeps smoothly along
each scan line and reverses at swath edges. Where flight lines overlap, they
interleave.

## Source and license

- Scottish Public Sector LiDAR Phase I (Scottish Government, SEPA, Scottish
  Water). Blom collected it between March 2011 and May 2012 over 10 collection
  areas at about 2 points/m². It was delivered as LAS 1.2 point data record
  format 1 (TerraScan), and the portal serves it as LASzip (compressor 2,
  50,000-point chunks).
- Bucket: `https://srsp-open-data.s3.eu-west-2.amazonaws.com/`, prefix
  `lidar/phase-1/laz/27700/gridded/` (12,464 tiles, 68.5 GB, listed
  2026-10-08).
- License: Open Government Licence v3. The portal API
  (`https://api.remotesensing.data.gov.scot/search/collection/scotland-gov/*`,
  collection `scotland-gov/lidar/phase-1/laz`) gives this useConstraints:
  "Crown copyright Scottish Government, SEPA and Scottish Water (2012). Open
  Government Licence v3". **Phase II on the same portal is under the
  Non-Commercial Government Licence.** `download.sh` refuses any key outside
  `lidar/phase-1/laz/`.

## Selection (scripts/discover.py, maintainer-only)

Range-read probes showed that **several Phase I collection areas were
delivered with the scan angle byte set to 0 in every point**: Orkney (HY), the
Inverness/Moray/Aberdeenshire areas (NH, NJ, NK), the Lochaber/Oban areas (NM,
western NN), mid-Argyll (NR8xxx), and the northern NO tiles. In those tiles
the first, middle and last chunks are all zero, and a full NH7588 decode is
100% zero. In the other areas every probed tile carries a real sweep of about
±25°. No probed tile mixed the two.

`discover.py` lists the prefix and takes 128 candidates evenly spaced over
the sorted key list. For each one it decodes only the first chunk, via byte
ranges. It keeps a candidate when that chunk's scan angle is not constant
(the zeroed tiles have exactly one value). 88 tiles were kept and 40 dropped.
The kept tiles cover NN (east), NO, NS, NT, NX and NY, which is the southern
and central collection areas. The recipe therefore does **not** cover all
10 collection areas: the field simply does not exist in the zeroed ones.
`scripts/tiles.tsv` pins key, size, ETag, sha256 (from the first verified
download, 2026-10-08) and point count;
`scripts/discovery_log.tsv` records every candidate and why it was kept or
dropped.

## Pipeline

- `download.sh`: one-byte liveness GET, then resumable curl of the 88 keys.
  `scripts/validate_downloads.py` then checks the exact size, the S3 ETag
  (plain MD5, or the multipart MD5 with 8 MiB parts), sha256 if pinned, LAS
  1.2, PDRF 1 with the compression bit, record length 28, LASzip compressor 2
  with POINT10 v2 + GPSTIME11 v2, and the pinned point count. It writes
  `download_inventory.json` with each tile's sha256. Expected download is
  433,958,092 bytes.
- `build.sh`: local only. `scripts/extract_scan_angle.py` decodes every
  chunk with `tools/laz/laszip.py` `iter_chunks`, writes byte 16 of each
  28-byte record unchanged to `<tile>.bin`, and writes `samples.jsonl` and
  `ingest_stats.json` (per-tile histograms). A tile is a fatal error if it has
  fewer than 5 distinct values, one value holding more than half the points,
  a span under 10°, or any value outside -90..+90.
- `verify.sh`: `scripts/verify_samples.py` re-decodes every tile, reading the
  angle through a signed memoryview, and requires byte-identical samples. It
  recomputes the same degeneracy policy and checks the index typing, the
  one-to-one match between tiles and samples, duplicate contents, the floors,
  the 1 GB cap, and the manifest `sample_count`/`total_size_bytes`. It prints
  the realized angle range.

Realized output (2026-10-08): 88 samples and 151,122,545 int8 values
(= bytes). The median is 1,759,592.5 values per tile, the range 124,504 to
3,531,022. Scan angle runs from -29 to +29°. The per-tile span is 15 to 58°
(median 50). Zeros make up 2.0% of all values (at most 4.5% in any tile), and
no single value holds more than 15.5% of any tile. 71 tiles were written by
TerraScan and 17 were re-zipped by LASzip DLL 2.4. All share the same
PDRF-1/28-byte layout.

Decoding is pure-Python (about 110 k points/s per worker). Build and verify
use `SRSP_WORKERS` processes (default `min(16, cpu_count)`).
