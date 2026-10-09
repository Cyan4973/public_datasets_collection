# SHOALS-1000T Blue Hill Bay GPS time float64 development

## Outcome

Accepted `noaa_shoals1000t_bluehillbay_topobathy_gps_time_f64`. It collects the native float64 `GPS Time` field from every point of all 92 published COPC tiles of NOAA Digital Coast project 8526: the SHOALS-1000T part of the 2017 Maine Coastal Program / NOAA OCM airborne lidar bathymetry survey of Blue Hill Bay, Maine, flown by Fugro.

The quantity and modality are the same as the accepted `dc_lidar_2015_gps_time_f64`: LAS GPS time stored as float64. The content is new: a different sensor regime and a different archive.

| | `dc_lidar_2015_gps_time_f64` | this recipe |
|---|---|---|
| sensor | conventional topographic scanner | 2.5 kHz bathymetric lidar |
| returns | multiple | one per pulse record |
| record order | acquisition order | COPC octree-node order (monotone runs per node) |
| epoch | about 1.1e8 s | about 1.83e8 s |
| archive | DC LiDAR 2015 bucket | NOAA NODD bucket |
| samples | 3 | 92 |

Novelty kind: `new_content_same_modality`. Measured breadth: OK. The nearest family is downstream `osm_daily_way_references_i64` at distance 0.0641. Local `dc_lidar_2015_gps_time_f64` sits at 0.0795 with 6.1% compression loss, above both redundancy thresholds.

## Source and rights

- **Source:** NOAA NODD bucket `noaa-nos-coastal-lidar-pds`, prefix `laz/geoid18/8526/`, anonymous HTTPS.
- **Tiles:** 92 `*.copc.laz` objects totalling 113,122,575 bytes, all last modified 2025-07-07. `sources.tsv` pins each one by key, size, MD5 (the single-part ETag) and SHA-256, plus the STAC `pc:count` and GpsTime statistics.
- **Provenance only:** the project metadata XML (70,290 bytes, SHA-256 `da905610…beedc`).
- **License:** the AWS Open Data registry entry for NOAA Coastal Lidar says "NOAA data disseminated through NODD are open to the public and can be used as desired." NOAA requests attribution and forbids implying endorsement. The project ISO metadata gives "Access Constraints: None"; its use constraints are advisory only. This is the same basis as the accepted `noaa_coastal_maine_topobathy_classification_u8`.
- **Discrepancy:** the STAC items' non-SPDX `CC-BY-1.0` tag is documented and requires nothing beyond attribution.

## Shape and conversion

One natural record is one COPC tile, and each tile becomes one sample.

Each tile is decoded with the repository's `tools/laz/laszip.py` (LASzip compressor 3, layered POINT14 v3, variable COPC chunks). Bytes 22..29 of every 30-byte PDRF 6 record are copied bit-exact, in stored order, into a raw little-endian float64 array.

Checks run for every tile:
- LAS 1.4, PDRF 6, `global_encoding` 17 (adjusted standard GPS time);
- the COPC info VLR is present;
- decoded point count equals the header count and the STAC `pc:count`;
- all values are finite;
- decoded min/max are bit-identical to the COPC info gpstime extent;
- min/max/mean agree with the STAC statistics;
- the tile is not constant.

Index min/max come from the stored float64 values. Nothing is filtered or dropped.

## Accepted output

| | |
|---|---|
| samples | 92 (the whole published 8526 population) |
| primary values | 25,298,628 |
| primary bytes | 202,389,024 |
| sample size | 468 to 978,629 values, median 255,850.5 |
| samples under 1,000 values | 1 (natural tile `20170705_tile_538000_4903000`, kept) |
| value range | 182,462,362.807 to 183,316,601.673 s |
| COPC node chunks | 881 |
| backward steps | 781, all at chunk boundaries |
| exact consecutive repeats | 18.9% |
| distinct values per tile | 76.3% |
| scanner channel | constant per tile: 0 in 27 tiles, 2 in 65 |
| aggregate SHA-256 of sample SHA-256s | `d2eb8b823176652a8581abad13ecf69a5e4a89708c4396d0c0e5502eecac6ddc` |
| zlsim own ratio | 15.68 |

## Judge checks

- **Gate:** `gate.py` passed with no warnings, matching the totals above.
- **Reproducibility:** I ran `verify.sh` myself and it exited 0 (`verify ok samples=92 values=25298628 bytes=202389024 median=255850.5`). build.sh reads only local downloads.
- **Population:** the live S3 listing for the 8526 prefix is not truncated and holds 92 direct `.copc.laz` objects totalling 113,122,575 bytes. Every size and ETag matches `sources.tsv`.
- **Bytes:**
  - I unpacked samples with `struct` across the size range and both channels. The dominant delta is 0.0004 s, which matches the 2.5 kHz pulse rate; there are also 0.8, 1.0 and 1.2 ms steps and 1-ulp (2^-25) jitter.
  - About a third of the values fall on whole milliseconds. This is native structure, the same in every tile.
  - fp64 is the native width; the mode share of 0.0001 means there is no fill.
  - I re-decoded two tiles independently. Inside-chunk backward steps are 0 and all records are return 1 of 1, which supports a correct decode of the GPS-time layer.
  - All 92 sample hashes are unique. Adjacent tiles share 0.02–0.05% of distinct values.
- **Homogeneity:** timing statistics by channel agree (channel 0 vs channel 2):
  - ms-quantized fraction: 0.34 vs 0.32
  - 0.4 ms-step fraction: 0.41 vs 0.39
  - repeat fraction: 0.21 vs 0.18

  The spread is similar on all three survey days.
- **Rights:** I opened the AWS registry page myself (bucket ARN listed, no AWS account required) and grepped the downloaded ISO metadata for its constraints. No script contains credentials.
- **Novelty:**
  - `novelty.py --url/--terms` found only other NOAA projects (10423 at u8, 8727 at u16) and `dc_lidar_2015_gps_time_f64` (local and downstream).
  - `--type/--instrument/--archive` found no family with the same instrument line or archive collection.
  - zlsim verdict OK, with local `dc_lidar_2015_gps_time_f64` at distance 0.0795 and loss 0.061, above the 0.05 / 3% thresholds.
