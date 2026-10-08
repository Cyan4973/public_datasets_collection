# UMich NCLT Velodyne HDL-32E revolution x,y,z (native scaled uint16)

This recipe collects LiDAR point coordinates from the University of Michigan
North Campus Long-Term (NCLT) dataset. The source is a Velodyne HDL-32E
mounted upside down on a Segway robot. The recipe uses one session,
2013-01-10. One sample is one published `velodyne_sync/<utime>.bin`
revolution file, emitted as an `N x 3` little-endian uint16 array of the
publisher's own `x, y, z` codes (interleaved per hit, in source hit order).
Metres are `code * 0.005 - 100`: a 5 mm lattice offset by 100 m, so code
20000 is 0 m.

## Attribution and license (ODbL 1.0 + DbCL 1.0)

NCLT is by Nicholas Carlevaris-Bianco, Arash K. Ushani and Ryan M. Eustice
(University of Michigan, Perceptual Robotics Laboratory):

> N. Carlevaris-Bianco, A. K. Ushani, and R. M. Eustice, "University of
> Michigan North Campus Long-Term Vision and Lidar Dataset", International
> Journal of Robotics Research, 35(9):1023-1035, 2016.
> http://robots.engin.umich.edu/nclt/

License text from http://robots.engin.umich.edu/nclt/index.html#license
(fetched 2026-10-06):

> The NCLT Dataset is made available under the Open Database License
> (available here). Any rights in individual contents of the database are
> licensed under the Database Contents License (available here). In short,
> this means that you are free to use this dataset, share, create derivative
> works, or adapt it, as long as you credit our work, offer any publically
> used adapted version of this dataset under the same license, and keep any
> redistribution of this dataset open. When using the NCLT Dataset, please
> credit our work by citing the paper above.

The two "here" links point to http://opendatacommons.org/licenses/odbl/1.0/
and http://opendatacommons.org/licenses/dbcl/1.0/.

Share-alike: the emitted samples are an adapted database derived from NCLT.
The adaptation keeps only the x, y, z codes of every 5th revolution of one
session, and drops intensity and laser_id. Anyone who publicly uses or
redistributes these samples must credit the NCLT authors as above, offer the
adapted database under ODbL 1.0, and keep it open. Individual contents remain
under DbCL 1.0.

## Source

- Object: `https://s3.us-east-2.amazonaws.com/nclt.perl.engin.umich.edu/velodyne_data/2013-01-10_vel.tar.gz`,
  linked from the NCLT download table. It is 2,926,183,916 bytes,
  Last-Modified Tue, 27 Sep 2022 11:37:44 GMT, with S3 multipart ETag
  `"3c9d1400e8ccec9c40bdd757221ad172-349"`. The parts are 8,388,608 bytes
  (348 full parts plus a final 6,948,332-byte part), confirmed with
  `?partNumber=1` and `?partNumber=349` HEAD requests. 2013-01-10 is the
  smallest of the 27 Velodyne tarballs (the others are 12 to 22 GB).
- Layout: a gzip of a GNU tar. The first member is
  `2013-01-10/velodyne_hits.bin` (2,771,041,792 bytes): the raw per-packet
  stream in the sensor frame, with a 24-byte header per packet starting with
  the 4 x `0xAD9C` magic. It is followed by the `2013-01-10/velodyne_sync/`
  files. Because the sync files come after the 2.77 GB hits member, no byte
  range can reach them without the whole preceding gzip stream. The recipe
  therefore downloads the whole object and streams it without extracting
  anything.
- Evidence that the sync members exist, gathered before the full download
  and reproducible with `discover.sh` / `scripts/probe_tail.py`: a
  raw-inflate resync on the last 2 MiB of the object decoded tar headers for
  `velodyne_sync/1357848261417566.bin` through `.../1357848263017383.bin`.
  These are 0.2 s apart (5 Hz), 316,576 to 331,320 bytes each (39,572 to
  41,415 hits), with laser_id 0..31 and codes 0..34,972. The archive ends
  with 7,168 bytes of tar zero padding. The gzip ISIZE trailer is 314,947,584
  (uncompressed size mod 2^32, consistent with about 4.61 GB uncompressed).

### What a velodyne_sync file is (publisher's representation)

From the NCLT paper, section 7.3: "The velodyne_sync directory contains a
list of files, one associated with each image. Each file is named according
to the image with which it is associated (UTIME.bin). Each file contains one
revolution's worth of Velodyne hits (corresponding to the previous 0.1
seconds), these points are motion compensated for the Segway's egomotion
during the scan and then recorded in the Segway body frame. Each point is
written using the 8 byte format described above."

The 8-byte hit record is `uint16 x, uint16 y, uint16 z, uint8 intensity,
uint8 laser_id`, all little-endian. The paper explains the coding: "we scale
each of x, y, z, to an integer between 0 and 40000 by adding 100 m and
discretize the result at 5 mm". The publisher's `read_vel_sync.py` decodes it
as `x = x_s * 0.005 - 100`.

The body frame is "centered on the axle between the Segway's wheels with x
pointing forward, y to the right, and z down". These coordinates are
therefore not raw sensor-frame measurements. They are the publisher's pinned
per-revolution product: motion-compensated, transformed to the body frame,
and then quantized. The recipe copies the published codes unchanged.

## Selection and conversion

- Only session 2013-01-10. `velodyne_hits.bin`, Hokuyo data, imagery and
  other sessions are not used, so the family has one sensor, one platform,
  one encoding and one processing chain.
- The archive holds 5,120 `velodyne_sync` files, from utime
  1357847238332442 to 1357848263017383 (1,024.7 s, spaced 0.2 s apart; 5
  gaps are about 0.4 s). They are sorted by the utime in their file name and
  ranks 0, 5, 10, ..., 5115 are selected (stride 5): 1,024 files, one
  revolution per second of the session. Taking every file would give about
  1.38 GB, over the 1 GB cap. Stride 5 gives 277 MB, inside the 100 to
  500 MB band the screener asked for. The robot keeps moving: for each pair
  of consecutive selected samples (1 s apart), the Jaccard overlap of the 1 m
  x/y cells occupied within 30 m ranges from 0.21 to 0.83 (median 0.46).
  This is a one-off scratch check, not part of verify.sh. No run of
  stationary near-duplicate scans was found.
- A selected file with fewer than 1,000 hits would be skipped and listed in
  `build_stats.json` (`skipped_below_min_hits`), with no neighbour
  substituted. None was skipped: the smallest of all 5,120 files has 13,869
  hits.
- Conversion: for each selected member, `N = size / 8` hits. Bytes 0..5 of
  every hit record (x, y, z) are copied into an `N x 3` point-major uint16
  array. Intensity and laser_id are dropped and nothing auxiliary is emitted.
  Samples are written to
  `samples/umich_nclt_velodyne_hdl32e_xyz_u16/nclt_velodyne_sync_xyz_u16/<utime>.bin`.

## Missing values and source quirks (kept as published)

- No-return shots are absent upstream (the upside-down mount makes many
  beams point at the sky), so `N` varies with the scene. Across all 5,120
  files: 13,869 to 215,633 hits, median 45,171. Across the selected samples:
  p01 20,218, p50 45,171, p99 82,717, max 178,951. Dense files are
  close-range scenes in which almost every beam returns (four inspected dense
  files have median ranges of 4.8 to 7.0 m, against 7.9 and 12.8 m in two
  typical files).
- Out-of-range hits: the paper says hits with an out-of-range measurement
  "are set to (0; 0; 0) in the sensor frame". The sync files are
  motion-compensated and transformed to the body frame after that, so these
  hits do not map to one fixed code (in particular not to 20000, 20000,
  20000). They are not identifiable and are kept.
- Files holding more than one revolution: the paper says each file is "one
  revolution's worth" (the previous 0.1 s), but 33 of the 5,120 files hold
  about three. The diagnostic is the busiest laser_id: in these files it has
  7,291 to 8,168 hits, against at most 2,747 in every other file (p99 2,726),
  and its azimuth wraps three times instead of once. The files have 61k to
  216k hits, and 12 of them fall within one 14 s stretch that ends 17 s
  before the end of the session. 10 of them are
  among the selected samples. They are the same sensor, encoding, frame and
  publisher process, and they are kept as the published records rather than
  filtered by a local threshold.
- Files with no azimuth wrap: in 135 files (24 selected) the busiest laser's
  azimuth never crosses the +-180 degree seam. The revolution either starts
  at the seam or is partial. These files have 13.9k hits upward and are
  kept.
- The per-sample index carries `max_hits_per_laser`, `busiest_laser_id` and
  `busiest_laser_azimuth_wraps`. The azimuth is `atan2(y - 20000, x - 20000)`
  about the body origin, and a wrap is a step of more than pi between
  consecutive hits of that laser. `build_stats.json` holds the population
  counts and the utime lists. These fields are informational and verify
  recomputes them independently.
- Lattice-floor codes: the pre-download tail probe found z code 0 (-100 m)
  on laser_id 15 in 3 of the last 9 files (895 to 2,097 hits each), and y
  codes 0 to 60 on a few far returns. This looks like clamping at the bottom
  of the 0..40000 range. Those files are not selected. No selected sample has
  any code below 1,959, so the realized output has no z code 0 hits. The
  index and stats would count them (with the laser_ids involved) if a
  selection contained any.
- Nothing is filtered, clipped, reordered or imputed. Fatal in build and
  verify: record framing not a multiple of 8 bytes, laser_id above 31, any
  code above the documented 40000, a constant sample or a constant axis, or a
  hash mismatch.

## Acquisition and validation

`download.sh` fetches the whole object with resumable curl into a `.part`
file: `-C -`, stall detection via `--speed-limit 1024 --speed-time 120`, and
no `--max-time`. curl's own `--retry` truncates back to where that curl run
started, so internal retries are kept at 3 for connection failures. An outer
loop of up to 12 curl runs resumes from the current `.part` size. It then
checks:

1. A one-byte range GET returns 206, the Content-Range total, the pinned
   ETag and the pinned Last-Modified.
2. The exact size, and the S3 multipart ETag recomputed locally (MD5 of the
   349 part MD5s). The SHA-256 is recorded in `archive_receipt.json`.
3. `scripts/nclt_tar.py scan` streams gzip + tar to EOF, so the gzip module
   checks CRC32 and ISIZE. It requires exactly one `velodyne_hits.bin` of the
   pinned size starting with the packet magic, at least 4,000 sync members
   with unique utimes, record framing in multiples of 8 bytes, and every
   laser_id at most 31. Only zero bytes may follow the tar end marker. It
   writes `members.tsv` with name, size, hit count, laser_id max, code max
   and SHA-256 for every member.
4. Only then is the `.part` file renamed.

The tool's `self-test` (run first) exercises all of these checks on
synthetic archives, including corrupted CRC, bad framing, laser_id 32, a
wrong hits magic or size, truncation, and too few members.

`build.sh` (`scripts/build_samples.py`) reads `members.tsv`, computes the
stride selection, and streams the archive once. For each selected member it
checks the SHA-256 against `members.tsv` and writes the sample. It also
requires the set of sync members in the stream to equal `members.tsv`, and
reads to gzip EOF.

`verify.sh` (`scripts/verify_samples.py`) does not reuse build code and does
not trust `members.tsv`. It re-streams the archive and takes its own census
of all sync members. It re-decodes each indexed member with a different
method (`array('H')` over the whole record stream, columns 0..2 of every
4-word record) and byte-compares the result with the sample. After the
stream it re-derives the stride and skip selection and requires the index to
match it exactly. It also checks the archive SHA-256 pinned from the first
download (`92118ba5dc8e197eb0dfd817a006b1acc20ff1efb2fa53be02f61d40d6438ccb`),
index fields, file inventory, SHA-256, per-axis min/max from the stored
uint16 codes, the z code 0 counts, and the busiest-laser diagnostics
(recomputed with `bytes.count`). It finishes with the stats file, the
aggregate hash, and the manifest's `sample_count` and `total_size_bytes`.

All three stages were exercised on a synthetic archive built from the 8 real
tail revolutions plus synthetic tiny and empty ones, with shuffled archive
order. Verify was confirmed to reject a flipped sample bit, an extra file, a
deleted sample, a wrong stride and a changed skip threshold. On a 1 GB
synthetic archive, scan, build and verify each took about 8 to 10 s. On the
real archive: download 100 s, scan 43 s, build 48 s, verify 39 s.

## Scope

Realized (2026-10-06):

- Archive: 2,926,183,916 bytes, SHA-256
  `92118ba5dc8e197eb0dfd817a006b1acc20ff1efb2fa53be02f61d40d6438ccb`,
  multipart ETag verified. It decompresses to 4,609,914,880 bytes:
  `velodyne_hits.bin` plus 5,120 sync files (1,834,968,048 bytes, 229,371,006
  hits) and no other members. The maximum code in any sync file is 37,848.
- Output: 1,024 samples, 46,219,538 hits, 138,658,614 uint16 values,
  277,317,228 bytes. Median 135,510 values per sample; range 41,607 to
  536,853 values.
- Codes: 1,959 to 37,120 overall. By axis: x 1,959 to 37,028 (-90.2 to
  +85.1 m), y 2,987 to 37,120 (-85.1 to +85.6 m), z 11,356 to 22,559 (-43.2
  to +12.8 m, z down).
- The SHA-256 of all samples concatenated in index order is
  `735534d4e23b915f0431feb531cc07e1d5b1e864bfd1dc4da673cea9ebd5578a`.

Disk use under `.data/*/umich_nclt_velodyne_hdl32e_xyz_u16`: 3,205,337,822
bytes (download 2,927,004,064; samples 277,358,240; index, stats and logs
about 1 MB). Nothing else is extracted, so this is under the 5 GB
per-candidate cap.

## Novelty

There is no NCLT material anywhere in the local corpus, staging, registry or
downstream mirror. The nearest family is `goose_vls128_lidar_scan_xyz_f32`:
vehicle roof LiDAR xyz in the sensor frame, natively float32, off-road. This
family is natively 16-bit. It is a fixed-point lattice (5 mm, offset binary)
from a different sensor (HDL-32E), on a different platform (campus Segway),
in a different frame (motion-compensated body frame). The other local 16-bit
LiDAR family, `dc_lidar_2015_intensity_u16`, holds aerial return intensities,
not coordinates. This is the first 16-bit LiDAR point-coordinate family.
LiDAR xyz as a modality already exists at 32-bit, so the novelty is a new
source at its native width, not a new modality.

## Run

```bash
bash staging/umich_nclt_velodyne_hdl32e_xyz_u16/download.sh
bash staging/umich_nclt_velodyne_hdl32e_xyz_u16/build.sh
bash staging/umich_nclt_velodyne_hdl32e_xyz_u16/verify.sh
```
