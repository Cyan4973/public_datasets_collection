# OSIRIS-REx OLA Level-2 Bennu lidar return XYZ (float64)

This recipe collects the Bennu-centred, body-fixed x, y, z coordinates (in
metres) of individual laser returns measured by the OSIRIS-REx Laser
Altimeter (OLA). They are the native `IEEE754LSBDouble` fields `x`, `y`, `z`
of the OLA Level-2 calibrated science tables (`*_ola_scil2id*.dat`, collection
`urn:nasa:pds:orex.ola:data_calibrated_v2::1.0`) archived by the NASA PDS
Small Bodies Node. Each published scan product becomes one sample: an N x 3
little-endian float64 array, with one row per valid return, in source order.

    bash staging/orex_ola_l2_lidar_point_xyz_f64/download.sh   # ~947 MB, host ~0.4 MB/s
    bash staging/orex_ola_l2_lidar_point_xyz_f64/build.sh
    bash staging/orex_ola_l2_lidar_point_xyz_f64/verify.sh

`discover.sh` documents how `sources.tsv` was resolved. It fetches only
listings and labels. Run it with `PROBE_FLAGS=1` to re-sample the flag mix
that justifies the excluded phases.

## Scope rule

The rule takes every `data_calibrated_v2` product in the `recon_b` and
`recon_c` phase directories whose label `file_size` is below 200,000,000 bytes.
That gives 44 products:

| phase | products | records each | .dat bytes |
|---|---|---|---|
| recon_b (2020-01-27 .. 2020-02-10) | 42 | 97,858 .. 97,967 | 764,997,912 |
| recon_c (2020-03-03, 2020-05-26) | 2 | 356,965 and 618,490 | 181,434,630 |
| total | 44 | 5,088,347 | 946,432,542 |

Every selected product is a High Energy Laser (`laser_selection` 0) linear
scan (`scan_mode` 1) at about 105 Hz. The build makes any kept record in a
different mode fatal, so the family is one instrument mode. The size bound
excludes the other 21 recon_b products (323 MB to 9.1 GB). The two that were
probed (06031 and 06052) are Low-Energy-Laser scans at about 10 kHz.

Phases that were probed and are not used:

- `preliminary_survey` (8 products, 89–107 MB, about 760 MB in total). These
  are High-Energy linear passes from about 7 km. Of 150 sampled records per
  product, 0–1 were valid returns: about 99.5% are no-return records (flag
  2/102), because most shots miss the 500 m asteroid. All 8 together would add
  only on the order of 10^4 points for 760 MB of download, so they are
  excluded.
- `sample_collection` products below 200 MB (00040, 00041, 00042). All 150
  sampled records of each are no-return. The 422 MB product 07000 is above the
  bound.
- `orbit_a` (380 MB), `detailed_survey` (202–305 MB) and `orbit_b`
  (911 x 594 MB) are above the size bound.
- Collections never touched: `data_calibrated` (v1, superseded), the
  `data_calibrated_l2a_v20`/`v21` strip-adjusted L2A products, and the L0/L1
  collections. The recon_b and recon_c products exist only in the v2
  collection: they have LIDVID version 1.0 and were created on 2021-10-25 with
  the refined calibration. v1 has no recon directories.

## Format and conversion

Each PDS4 label describes one `Table_Binary` at offset 0, with `records` x
186-byte records of 23 fields. `scripts/ola_l2.py` parses the label with
`xml.etree` and asserts all of the following:

- the LID belongs to the data_calibrated_v2 collection, and the LIDVID is
  pinned and listed in the collection inventory;
- `record_length` = 186, `fields` = 23, `groups` = 0;
- `x`/`y`/`z` are at `field_location` 115/123/131 as 8-byte
  `IEEE754LSBDouble` in m;
- `file_size` = `records` x 186.

The location and type of `flag_status` (byte 73, `SignedLSB2`),
`laser_selection` and `scan_mode`, and the meaning of the flag codes, are read
from the label rather than hard-coded.

For every record with a kept flag, bytes 114..137 are copied unchanged into
`samples/orex_ola_l2_lidar_point_xyz_f64/ola_l2_return_xyz_f64/<product>_xyz.f64`.
The source is already little-endian IEEE-754, so the output is bit-exact.

Sanity evidence from probed records:

- In the label, `elongitude`/`latitude`/`radius` equal the spherical form of
  (x, y, z) to about 1e-13 degrees, so the frame is Bennu-centred and
  body-fixed.
- `|point - spacecraft|` matches the measured `range` to about 1 m.
- |xyz| spans 213–281 m for all but 6 of the 5,087,058 kept points (see
  Missing values).
- 0 of 18,000 probed values are float32-exact, so the doubles carry full
  precision.

## Missing values

These are the label's flag_status codes and the policy for each:

| code | meaning | policy |
|---|---|---|
| 0, 100 | valid return (100: demodulator on) | kept |
| 1, 101 | valid return with overflow | kept |
| 2, 102 | no return | dropped |
| 3, 103 | missing sample | dropped |

No-return records still carry xyz, but it is computed from a sentinel range
of -1128.922153 mm and so lies roughly at the spacecraft position. That is
about 1 km from Bennu in recon B, about 7 km in the preliminary survey, and
up to about 2000 km in the excluded sample_collection products. Keeping
those records would inject junk points into the stream. The realized build
dropped 1,289 of 5,088,347 records (0.025%): 1,012 with flag 2 and 277 with
flag 102. No flag 1, 3, 101 or 103 occurs in the selected products.

All of the following are fatal in `download.sh` validation, `build.sh` and
`verify.sh`:

- an undocumented flag value or a changed code list;
- a kept record with non-finite xyz;
- a kept record whose mode is not High Energy Linear;
- a product with less than 90% kept records;
- more than 1% of kept points outside 150–350 m.

Kept points are never clipped or reordered. Per-product kept and dropped
counts go to the index and to `filtered/<id>/build_stats.json`.

Six valid-flag (flag 0) points do not lie on the surface:

| product | distance from centre | measured range |
|---|---|---|
| recon_b 06053 | 1,102.7 m | 151 m |
| recon_b 06056 | 934.4 m | 483 m |
| recon_b 06111 | 782.1 m | 344 m |
| recon_b 06060 | 755.3 m | 444 m |
| recon_b 06075 | 401.8 m | 532 m |
| recon_c 06500 | 345.2 m | (within band) |

The measured ranges are far shorter than the roughly 800 m to the surface,
so these are early returns from something between the spacecraft and Bennu.
The source flags them as valid returns, so they are kept as published. The
five outside 150–350 m are counted in `out_of_band_points`, which is well
under the 1% sanity limit.

## Realized output

| | value |
|---|---|
| samples | 44 (42 recon_b, 2 recon_c) |
| source records | 5,088,347 |
| kept points | 5,087,058 |
| values | 15,261,174 |
| bytes | 122,089,392 |
| points per sample | 97,054 to 618,490 |
| median values per sample | 293,746.5 |

The SHA-256 of all samples, concatenated in index order, is
`df1d2fd1bd7b3927bd1314a4f02d9247a9b22ffe8041d268d794d27ee4afd158`. The
download realized 947,272,329 bytes under `downloads/<id>/`.

## Index

`index/orex_ola_l2_lidar_point_xyz_f64/samples.jsonl` holds one row per
product. It has the required fields plus `sample_shape` [N, 3],
`point_count`, `phase`, `product`, `lidvid`, `start_utc`/`stop_utc`,
`source_records`, `flag_counts`, the dropped counts, the |xyz| range,
`out_of_band_points`, `source_dat_sha256`, `sha256`, and `min`/`max` computed
from the stored float64 values.

## Verification

`verify.sh` (`scripts/verify_samples.py`) does not import the build code. It
re-parses each label with its own reader and re-checks label SHA-256, .dat
size, inventory membership and the optional `payload_sha256.tsv` pins. It
then re-derives each sample by byte slicing and compares it byte for byte. It
re-applies the flag, mode, finiteness and |xyz|-band policy, rejects constant
samples or axes, and checks index fields, min/max, digests, the sample
directory inventory, the floors and cap, and the manifest totals.

## Caveats

- Recon B (range about 0.8 km) and Recon C (about 0.3 km) differ in footprint
  density and altitude. They do not differ in quantity, unit or frame: apart
  from the 6 early returns above, all points are surface positions 213–281 m
  from Bennu's centre.
- These are the L2 calibrated products, not the strip-adjusted L2A (v21)
  products that the OLA team recommends for final topography. Small
  systematic offsets between passes are therefore part of the material.
- The host serves at roughly 0.4 MB/s. `download.sh` resumes partial `.part`
  files with `curl -C -` and uses a stall-based speed limit, never
  `--max-time`, on the tables.
- PSI publishes no payload checksums. Label SHA-256 values and table sizes are
  pinned up front. Table SHA-256 values are pinned in `payload_sha256.tsv`
  after the first download; `download.sh` writes the computed list to
  `downloads/<id>/payload_sha256.computed.tsv`.

## License

The data fall under the NASA Science Mission Directorate open scientific data
policy (https://science.nasa.gov/researchers/science-data/science-information-policy/),
on the same basis as the accepted `nasa_pds_*` recipes. Cite: Daly, M.;
Barnouin, O.; Espiritu, R.; Lauretta, D.S., *OSIRIS-REx Laser Altimeter (OLA)
Bundle 5.0*, NASA PDS Small Bodies Node, doi:10.26033/g7ym-d692.
