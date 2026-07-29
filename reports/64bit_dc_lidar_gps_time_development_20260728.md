# DC LiDAR GPS-Time Float64 Development — 2026-07-28

`dc_lidar_2015_gps_time_f64` adds native binary64 acquisition-time streams from
airborne point-cloud records. It uses the same three public LAS tiles as the
accepted DC LiDAR classification recipe, but selects a different native field
and width: point-format-6 GPS time rather than uint8 categorical class codes.

The candidate was grounded against committed `datasets/*/manifest.toml`,
`attempts/dataset_status.tsv`, and `reports/accepted_recipe_audit.tsv`. The
existing local LAS files were inspected only after identifying the accepted
recipe and its exact stable dataset ID.

## Width and material validation

All three pinned files are uncompressed LAS 1.4 point data record format 6.
That format stores GPS time as an eight-byte IEEE-754 value at byte offset 22
of each 30-byte point record. The builder copies those eight bytes unchanged;
there is no decimal reformatting, integer widening, or locally generated data.

The downloader pins and validates exact public S3 URLs, byte sizes, and
SHA-256 hashes. When the accepted classification cache is present, it
hard-links the already-validated files rather than downloading another 650 MB.

## Realized output

Local build and independent source-byte verification passed:

- source tiles: `3`
- point format / record length: `6` / `30` bytes
- primary samples: `3`, one GPS-time stream per LAS tile
- primary values: `21,697,532`
- primary bytes: `173,580,256`
- median sample: `7,454,412` values
- sample range: `3,182,786` to `11,060,334` values

The full streams are not hash-like noise. Adjacent GPS times are nondecreasing
for `99.776%`, `99.432%`, and `99.846%` of the three samples. Exact repeated
adjacent times account for `2.069%`, `5.428%`, and `8.832%`, reflecting
multiple returns and acquisition ordering. A preliminary evenly sampled raw
zlib check produced ratios of approximately `0.40` to `0.46`.

Verification independently re-extracts offset-22 bytes from every LAS record
and compares them with every output byte while also checking float64
finiteness, sample counts, acceptance floors, and the 1 GB cap.
