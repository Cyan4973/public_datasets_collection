# OSIRIS-REx OLA L2 Bennu lidar return XYZ float64 development

## Outcome

Accepted `orex_ola_l2_lidar_point_xyz_f64`. The source is the NASA PDS Small Bodies Node OSIRIS-REx Laser Altimeter (OLA) bundle 5.0, collection `urn:nasa:pds:orex.ola:data_calibrated_v2::1.0`.

This is the corpus's first planetary laser-altimetry point geometry and its first lidar point-coordinate family at 64 bits. The nearest accepted families are:
- `goose_vls128_lidar_scan_xyz_f32`: a car-mounted Velodyne, sensor frame, float32;
- `dc_lidar_2015_gps_time_f64`: lidar time stamps, not geometry;
- `nasa_pds_mola_megdr_i16`: a gridded topography raster, not per-return points.

Novelty kind: new source. The modality, lidar point xyz, already exists at 32 bits.

## Source and rights

- Source: https://sbnarchive.psi.edu/pds4/orex/orex.ola/data_calibrated_v2/{recon_b,recon_c}/, served by anonymous HTTPS.
- Bundle: OSIRIS-REx Laser Altimeter (OLA) Bundle 5.0, doi:10.26033/g7ym-d692 (Daly, Barnouin, Espiritu, Lauretta). `bundle_ola.xml` lists `data_calibrated_v2::1.0` as a member.
- Collection inventory: 79,790 bytes, SHA-256 `19641a0bc30d1499885077023ede6c82b33ed48e5970a490ac990a32d8c7df45`. Every pinned LIDVID must be a primary member.
- Pinning:
  - 44 labels, with size and SHA-256 in `sources.tsv`;
  - 44 `.dat` tables, 946,432,542 bytes in total, with sizes in `sources.tsv` equal to label records × 186;
  - per-table SHA-256 from the first download in `payload_sha256.tsv`, because PSI publishes no payload checksums.
- License: NASA SMD Open Scientific Data Policy. NASA holds SMD data "as a public trust", requires it to "be made publicly available", and states no use restriction. This is the same basis as the accepted `nasa_pds_cassini_vims_qube_i16`, `nasa_pds_magellan_fmidr_sar_u8` and `nasa_pds_mastcamz_raw_i16`. OLA was a Canadian Space Agency contribution distributed through NASA PDS; `nasa_pds_sharad_radargram_f32` is the precedent for an ASI-contributed instrument. The labels and the DOI landing page carry no restriction.

## Shape and conversion

Each natural record is one published OLA L2 `scil2id` scan product: a PDS4 label plus a binary table of 186-byte, 23-field records.

The scope rule, documented by `discover.sh`, is every `data_calibrated_v2` product in `recon_b` and `recon_c` whose label `file_size` is below 200,000,000 bytes:
- 42 Recon B products, about 15.5 minutes and about 97.9k records each, January–February 2020, about 0.8 km range;
- 2 Recon C products, the Nightingale and Osprey site passes, 356,965 and 618,490 records, about 0.3 km range.

All selected records are High-Energy Laser (`laser_selection` 0), linear scan (`scan_mode` 1) at about 105 Hz. Any other mode is fatal.

Excluded phases:
- The 21 larger recon_b products, 323 MB to 9.1 GB; the two probed are Low-Energy-Laser scans at about 10 kHz.
- `preliminary_survey` and the small `sample_collection` products, which are essentially all no-return records.

The labels are parsed with `xml.etree`, and the recipe asserts:
- `record_length` 186, 23 fields, 0 groups;
- x/y/z at bytes 115/123/131 as 8-byte `IEEE754LSBDouble` in m;
- flag codes keep {0, 1, 100, 101} and drop {2, 3, 102, 103}.

For each kept record, bytes 114..137 are copied unchanged into one N×3 little-endian float64 array per product, in source order. Records flagged 2/102 (no return) are dropped: their xyz is computed from a sentinel range of −1128.922153 mm and lies at the spacecraft. That is 1,289 records, 0.025%: 1,012 with flag 2 and 277 with flag 102. Codes 1/3/101/103 do not occur.

Six source-valid points are not on the surface; they have saturated intensity and short ranges. They are kept as published and counted per product as `out_of_band_points`. Range, az/el, intensities, the redundant lon/lat/radius form, spacecraft position, time strings and flags are not emitted.

## Accepted output

- Source products: 44 (42 recon_b, 2 recon_c)
- Source records: 5,088,347
- Kept points: 5,087,058 (3,873,296 flag 0 and 1,213,762 flag 100)
- Primary samples: 44
- Primary values: 15,261,174
- Primary bytes: 122,089,392
- Minimum sample: 291,162 values (97,054 points, recon_b 06056)
- Median sample: 293,746.5 values
- Maximum sample: 1,855,470 values (618,490 points, recon_c 06510)
- Realized download: 947,272,329 bytes, in 510 s
- Aggregate SHA-256 of samples concatenated in index order: `df1d2fd1bd7b3927bd1314a4f02d9247a9b22ffe8041d268d794d27ee4afd158`

The local build and the independent byte-for-byte verification both completed against the pinned files.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/orex_ola_l2_lidar_point_xyz_f64` passes with no warnings.
- **Verify:** I re-ran `bash staging/orex_ola_l2_lidar_point_xyz_f64/verify.sh` myself. It prints `verify_ok samples=44 points=5087058 values=15261174 bytes=122089392 median_values=293746.5`. The verifier does not import the build code.
- **Local-only build:** build.sh and the Python scripts make no network calls and contain no credentials.
- **Sample bytes:** I decoded six samples with `struct`.
  - 0 of 180,000 values are float32-exact, and all values are unique, so 64 bits is the native width.
  - The trailing-zero mantissa distribution is natural.
  - Axes span about ±290 m, and radius is 213–281 m except for the 6 documented points.
  - The median step between consecutive returns is 0.18 m in Recon B and 0.04 m in Recon C, consistent with linear scan lines.
- **Raw records:** I parsed 13,194 random valid records from all 44 `.dat` files with my own struct layout.
  - xyz equals the spherical lon/lat/radius fields to at most 1.3e-12°.
  - |p − sc| − range is 1.05–1.25 m, a constant offset.
  - Every record in every product is laser 0 / scan 1.
  - Dropped 2/102 records have the sentinel range and xyz within about 1 m of the spacecraft.
  - Exactly 6 valid points lie above 300 m radius, all with intensity_t0 = 16383.
- **Diversity:** product centroids cover all longitudes and latitudes from −86° to +73°. The maximum 10°-cell Jaccard overlap between products is 0.53, so there are no near-duplicates. The Recon C centroids fall on Nightingale (57°N, 41°E) and Osprey (13°N, 92°E).
- **Exclusion probe:** my own 60-record byte-range probe of `preliminary_survey/20181204_ola_scil2id01000.dat` returned 60 of 60 no-return records, which confirms that exclusion.
- **Rights:** I fetched the NASA SMD policy page, the DOI landing page and `bundle_ola.xml`, which lists `data_calibrated_v2::1.0` as a bundle 5.0 member.
- **Novelty:** novelty.py matched only this candidate across recipes, the registry, the ledger and downstream.
- **Aggregate digest:** I recomputed the aggregate SHA-256 and the min/median/max sample sizes from the sample files; they match the builder's figures.
