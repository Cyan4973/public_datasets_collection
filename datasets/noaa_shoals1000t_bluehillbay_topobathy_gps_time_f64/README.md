# NOAA/MCP 2017 Blue Hill Bay topobathy lidar (SHOALS-1000T, Digital Coast 8526): per-point GPS time, float64

This recipe collects the native float64 `GPS Time` field of every point in all
92 published COPC tiles of NOAA Digital Coast project 8526. The project is the
SHOALS-1000T part of the 2017 Maine Coastal Program / NOAA OCM airborne lidar
bathymetry survey of Blue Hill Bay, Maine, flown by Fugro. Each tile is one
sample, and the values are copied bit for bit.

## Source

- Bucket: NOAA Open Data Dissemination (NODD) `noaa-nos-coastal-lidar-pds`,
  prefix `laz/geoid18/8526/` (anonymous HTTPS).
- Tiles: the 92 `*.copc.laz` objects directly under the prefix. They total
  113,122,575 bytes and hold 25,298,628 points. All were last modified
  2025-07-07. `sources.tsv` pins each key, size, single-part MD5 ETag, STAC
  `pc:count`, STAC GpsTime min/max/mean, and the SHA-256 pinned from the first
  verified download (2026-10-08). `scripts/discover.sh` (S3 listing
  plus STAC item collection, metadata only) regenerates it.
- Sensor: the project metadata XML (also downloaded for provenance) gives
  "The system collects bathymetric LiDAR data at 2.5 kHz Pulse Repetition Rate
  for an approximated point density of 0.15 pts/m2". The concurrent Riegl
  VQ-820-G acquisition is a separate dataset (8525) and is **excluded**.
- Layout, checked for every tile by `download.sh`, `build.sh` and `verify.sh`:
  - LAS 1.4, point data record format 6, 30-byte records with no extra bytes.
  - `global_encoding` bit 0 set: GPS time is adjusted standard time, i.e. GPS
    seconds minus 1e9. Both probed tiles have value 17.
  - LASzip compressor 3 with the single item POINT14 v3 and variable (COPC)
    chunks.
  - The COPC info VLR is present.
  - STAC reports one return per pulse record and a constant scanner channel
    per tile (0 or 2), so the decoder never switches channel context inside a
    tile.

## License

The AWS Open Data registry entry (`noaa-coastal-lidar.yaml`) says: "NOAA data
disseminated through NODD are open to the public and can be used as desired.
... NOAA requests attribution for the use or dissemination of unaltered NOAA
data. However, it is not permissible to state or imply endorsement by or
affiliation with NOAA. If you modify NOAA data, you may not state or imply that
it is original, unaltered NOAA data." The project ISO metadata gives "Access
Constraints: None", with only no-warranty and distribution-liability
disclaimers.

**Discrepancy:** each STAC item has a property `license: CC-BY-1.0`. That is
not a valid SPDX identifier, and it asks for nothing beyond attribution. The
recipe ignores it and cites the NODD terms as authoritative. Attribution:
NOAA Office for Coastal Management; Maine DMR / Maine Coastal Program; Fugro.

## Conversion

1. `download.sh` fetches each tile with resumable curl into
   `$DATA_DIR/downloads/<id>/copc/`. It checks the size, MD5 (ETag) and pinned
   SHA-256, writes `download_inventory.tsv`, and validates every header,
   including that the point count equals STAC `pc:count`.
2. `build.sh` decodes each tile with the repository decoder
   `tools/laz/laszip.py` (`iter_chunks`; it is imported, not copied). It copies
   bytes 22..29 of every record unchanged into
   `$DATA_DIR/samples/<id>/shoals_gps_time_f64/<tile>_gps_time_f64.bin`, as raw
   little-endian float64 with one value per point. For each tile it checks:
   - decoded count equals the header count;
   - all values are finite;
   - decoded min/max are **bit-identical** to the gpstime extent in the COPC
     info VLR, which guards against desynchronisation of the GPS-time layer;
   - min/max/mean agree with the publisher's STAC statistics, within their
     10-significant-digit rounding;
   - the tile has at least 2 distinct values.

   Index min/max are computed from the stored float64 values.
3. `verify.sh` re-decodes every tile and re-extracts the field with
   `struct.iter_unpack("<22xd")`, a different code path from the build. It
   byte-compares each sample and re-checks the index fields, SHA-256, min/max
   and the manifest totals.

**Record order.** Values are in the stored order of the COPC file. That is
COPC octree-node order (points stored node chunk after node chunk), **not**
acquisition order. In the realized build, the 92 tiles hold 881 node chunks.
The series steps backwards 781 times in total, almost all at node boundaries;
within a node, times are close to ascending. 18.9% of consecutive values
repeat exactly (the same GPS time on adjacent records), and 76.3% of values
are distinct within their tile. One tile can contain several flight days: tile
time spans run from 4.5 minutes to 9.8 days, median 6.1 hours. The scanner
channel is constant within each tile: 0 in 27 tiles, 2 in 65.

## Scope (realized, build 2026-10-08)

| | |
|---|---|
| samples | 92 (one per tile, the whole published 8526 population) |
| values | 25,298,628 |
| primary bytes | 202,389,024 |
| sample size | 468 to 978,629 values, median 255,850.5 |
| value range | 182,462,362.807 to 183,316,601.673 s (adjusted standard GPS) |
| aggregate sha256 of sample sha256s | `d2eb8b823176652a8581abad13ecf69a5e4a89708c4396d0c0e5502eecac6ddc` |

One tile, `20170705_tile_538000_4903000` with 468 points, is below 1,000
values. It is **kept** because it is a natural record of the published
population, and the median floor clears by a wide margin. Three other tiles
have fewer than 10,000 points (3,119, 6,351 and 7,924).

## Nearest existing family

`dc_lidar_2015_gps_time_f64` holds GPS time from three uncompressed DC 2015
LAS tiles of a conventional topographic scanner, in acquisition order, with
epoch about 1.1e8 s. This recipe differs in several ways:
- the sensor is a 2.5 kHz bathymetric lidar, so inter-pulse deltas are
  roughly two orders of magnitude larger;
- there is one return per pulse record;
- the stored order is COPC node order;
- the epoch is about 1.83e8 s;
- it covers 92 tiles from a different archive.

Whether the bytes are distinct enough is for `zlsim.py` to decide; it is not
claimed here.

## Usage

```bash
bash staging/noaa_shoals1000t_bluehillbay_topobathy_gps_time_f64/download.sh
bash staging/noaa_shoals1000t_bluehillbay_topobathy_gps_time_f64/build.sh
bash staging/noaa_shoals1000t_bluehillbay_topobathy_gps_time_f64/verify.sh
```

Decoding runs at roughly 60,000 points/s (pure Python), so build and verify
each take about 7 to 10 minutes.
