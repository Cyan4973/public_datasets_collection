# DC LiDAR Intensity UInt16 Development — 2026-08-01

`dc_lidar_2015_intensity_u16` adds native two-byte laser-return intensity
streams from airborne point-cloud records. It uses the same three exact public
LAS tiles as the accepted DC LiDAR classification and GPS-time recipes, but
selects a previously absent native field and width: point-format-6 intensity
at byte offset 12.

The recipe succeeds the blocked `usgs_3dep_las_intensity_u16` discovery and
failed `pdal_sample_las_intensity_u16` Git-LFS attempt. The exact DC objects are
uncompressed LAS 1.4 files with pinned sizes and SHA-256 hashes, so neither S3
listing discovery nor LAZ tooling is required. The user-run downloader reused
the already validated accepted LiDAR cache without a network transfer.

## Realized output

Local build and source-byte verification passed:

- source tiles: `3`
- point format / record length: `6` / `30` bytes
- primary samples: `3`, one intensity stream per LAS tile
- primary values: `21,697,532`
- primary bytes: `43,395,064`
- median sample: `7,454,412` values
- sample range: `3,182,786` to `11,060,334` values
- realized value range: `0..255`
- distinct values per tile: `95`

Although LAS stores intensity as native little-endian `uint16`, all selected
values have a zero upper byte. This is intentionally preserved rather than
repacked to uint8: the family represents a real narrow-values-in-wide-slots
case for compression training. It is not claimed as a new LiDAR domain or a
new sample geometry; its justification is the previously absent native
return-intensity field and its different statistical structure.

The streams are locally correlated rather than categorical class runs or
monotonic timestamps. Exact adjacent repeats range from `13.15%` to `16.31%`,
while `67.64%` to `74.89%` of adjacent deltas have magnitude at most 16.
Per-tile empirical entropy ranges from approximately `6.13` to `6.21` bits per
value despite the 16-bit storage width.

Verification re-extracts bytes 12 and 13 from every 30-byte source point
record and byte-compares the full generated samples. It also checks source
layout, non-constant output, indexed ranges and cardinalities, sample counts,
acceptance floors, and the 1 GB primary-output cap.
