# Boreas Velodyne Alpha Prime LiDAR Per-Point Intensity (uint8)

Per-point calibrated return intensity from the 128-beam Velodyne Alpha Prime
roof lidar of the UTIAS ASRL Boreas test vehicle in Toronto. The recipe takes
264 complete published sweep files, 6 evenly spaced from each of the 44
original Boreas sequences (2020-11-26 to 2021-11-28: snow, rain, sun, night on
a repeated route). It emits one uint8 sample per sweep, one byte per returned
point, in native point order.

- Source: public bucket `s3://boreas` (AWS Open Data Registry), served
  anonymously from `https://boreas.s3.amazonaws.com/` and not requester-pays.
- License: CC BY 4.0. pyboreas `DATA_LICENSE.md`: "The Boreas and Boreas Road
  Trip datasets are licensed under a Creative Commons Attribution 4.0
  International Public License ("CC BY 4.0")." The AWS ODR entry says the same.
  **Attribution:** Boreas dataset, University of Toronto Institute for
  Aerospace Studies, Autonomous Space Robotics Lab (UTIAS ASRL). Cite Burnett
  et al., "Boreas: A Multi-Season Autonomous Driving Dataset", IJRR 2023,
  arXiv:2203.10168.

## Source format and conversion

The pyboreas devkit's `load_lidar` defines each `lidar/<timestamp_us>.bin`
file as N x 6 little-endian float32 values:
`x, y, z, intensity, laser_number, time`. The recipe keeps field 3
(intensity) only. The sensor reports intensity on its native 8-bit
calibrated-reflectivity scale (0-100 diffuse, 101-255 retroreflective), and
Boreas stores it as an exactly integral float. Writing it as uint8 is
lossless, and both build and verify assert that every value is an integer in
0..255. Violations abort the run; values are never clamped.

These fields are not emitted:
- x, y, z geometry.
- `laser_number`: the ring ID 0..127. It is checked as a sensor fingerprint
  and must be an integer in 0..127.
- The per-point time offset.

## Scope and selection

- Sequences: all 44 top-level `boreas-2020-11-*` .. `boreas-2021-11-*`
  prefixes, which form the original Boreas release with the Alpha Prime.
  Excluded: the 2022 sequences, the 2024/2025 Boreas Road Trip sequences
  (whose sensor suite adds an Aeva FMCW lidar), and the calibration runs.
  The bucket holds no machine-readable sensor-model metadata per sequence.
  The era restriction therefore rests on the pyboreas documentation. The
  verifier checks a structural fingerprint instead: every sweep has 6 fields
  and integral laser numbers in 0..127.
- Sweeps: `discover.sh` lists each sequence's `lidar/` prefix with
  ListObjectsV2 and follows continuation tokens. That gives 460,284 sweeps,
  8,054 to 18,775 per sequence. All are single-part uploads, so each ETag is
  the plain MD5, and every size is a multiple of 24. Within a sequence the
  sweeps are sorted by timestamp and indices `floor((2k+1) n / 12)`,
  k = 0..5, are taken.
- Pinned in `sources.tsv`: key, size, MD5, point count, and sweep index and
  count within the sequence.
- Download: 264 files, 1,334,877,072 bytes. Realized primary output:
  55,619,878 bytes, with 158,874 to 232,168 points per sweep. The extraction
  ratio is 1/24. No leaner source exists, because the intensity byte is
  interleaved in the float32 point records.

## Missing values and degeneracy

The sweep files contain only returned points, with no padding records.
Intensity 0 is a legitimate low-reflectivity reading and is kept. Any
non-finite field, out-of-range or non-integral intensity or laser number, or a
size that is not a multiple of 24 is fatal in all three scripts. `verify.sh`
rejects:
- constant samples;
- samples whose most common value covers more than 80% of points.

## Realized output and zero fraction per sample

The build produced 264 samples (6 from each of the 44 sequences), 55,619,878
uint8 values and bytes. The median sample holds 214,646.5 values; samples
range from 158,874 to 232,168 values.

- All 256 intensity values occur across the samples. The median sample has
  205 distinct values; the range is 99 to 256.
- Value 0 makes up 8.18% of all points, and values 1, 2 and 3 make up 6.96%,
  6.47% and 5.91%. The distribution is a smooth low-intensity mode with a
  long tail.
- Retroreflective returns (101-255) make up 0.85% of points.
- Per-sample zero fraction: minimum 0.72%, median 6.17%, maximum 48.09%. The
  most common value in any sample is always 0 or a small intensity. Its share
  ranges from 2.8% to 48.1%, with a median of 7.8%.
- 12 samples exceed 25% zeros. Nine of them come from the two 2021-01-26
  sequences, whose 12 sweeps range from 8.9% to 48.1% zeros. The other three
  are one sweep each from 2020-12-04 (25.6%), 2021-10-26 (29.6%) and
  2021-11-28 (26.4%).
- No sample is fill-dominated. verify.sh fails any sample whose most common
  value exceeds 80%.
- Every sample has all 128 laser numbers present. Time offsets lie within
  +/-0.054 s of the file timestamp, which is one 10 Hz revolution.

The scout's 23-45% zero estimate came from 48 KB windows of single
2021-01-26-11-22 and 2020-11-26-13-58 sweeps. Whole sweeps are usually much
lower.

Zero fraction of each sample, as a percentage of its points. Source:
`filtered/<id>/build_stats.json`, which also lists distinct values, mode,
min/max and ring count per sample.

| Sequence | Zero % of the 6 sweeps (timestamp order) | Distinct values (min-max) | Points (min-max) |
|---|---|---|---|
| boreas-2020-11-26-13-58 | 9.7 / 13.0 / 5.9 / 10.3 / 5.4 / 15.0 | 136-226 | 193955-223187 |
| boreas-2020-12-01-13-26 | 17.1 / 14.5 / 12.1 / 15.8 / 11.5 / 24.1 | 117-222 | 187965-221217 |
| boreas-2020-12-04-14-00 | 19.5 / 25.6 / 11.6 / 9.5 / 11.4 / 23.3 | 177-254 | 186525-219657 |
| boreas-2020-12-18-13-44 | 12.8 / 6.3 / 3.7 / 2.5 / 3.1 / 6.7 | 123-251 | 193892-217965 |
| boreas-2021-01-15-12-17 | 15.7 / 9.2 / 6.0 / 3.8 / 5.1 / 11.5 | 141-241 | 191249-219550 |
| boreas-2021-01-19-15-08 | 6.2 / 12.0 / 8.5 / 6.4 / 6.2 / 7.1 | 168-246 | 197322-228328 |
| boreas-2021-01-26-10-59 | 48.1 / 30.7 / 16.9 / 28.6 / 36.8 / 39.1 | 99-207 | 158874-214261 |
| boreas-2021-01-26-11-22 | 31.8 / 32.9 / 25.1 / 8.9 / 19.7 / 28.8 | 129-256 | 203360-230175 |
| boreas-2021-02-02-14-07 | 5.8 / 5.0 / 6.5 / 6.4 / 4.4 / 9.6 | 110-244 | 191144-228610 |
| boreas-2021-02-09-12-55 | 17.8 / 5.6 / 6.4 / 9.6 / 4.6 / 11.7 | 111-255 | 194119-221125 |
| boreas-2021-03-02-13-38 | 6.0 / 11.1 / 5.9 / 3.1 / 4.4 / 9.6 | 109-232 | 195196-221968 |
| boreas-2021-03-09-14-23 | 6.2 / 9.5 / 3.2 / 3.2 / 2.6 / 5.6 | 138-245 | 193286-221058 |
| boreas-2021-03-23-12-43 | 11.5 / 6.2 / 3.7 / 2.5 / 2.7 / 8.4 | 116-240 | 192798-216128 |
| boreas-2021-03-30-14-23 | 5.2 / 4.1 / 2.7 / 2.1 / 7.4 / 6.7 | 159-247 | 192622-211768 |
| boreas-2021-04-08-12-44 | 15.0 / 3.0 / 3.8 / 2.1 / 1.3 / 7.9 | 138-248 | 193840-220380 |
| boreas-2021-04-13-14-49 | 5.6 / 1.9 / 3.6 / 4.3 / 3.6 / 9.5 | 126-249 | 192138-219907 |
| boreas-2021-04-15-18-55 | 3.5 / 4.9 / 4.8 / 2.5 / 4.9 / 9.3 | 113-242 | 197396-223407 |
| boreas-2021-04-20-14-11 | 12.3 / 3.7 / 3.4 / 5.5 / 2.1 / 8.5 | 116-231 | 196598-221580 |
| boreas-2021-04-22-15-00 | 7.6 / 10.0 / 9.2 / 2.4 / 3.8 / 10.6 | 197-242 | 191028-217901 |
| boreas-2021-04-29-15-55 | 12.2 / 20.3 / 13.5 / 12.2 / 21.2 / 21.1 | 124-244 | 191572-218987 |
| boreas-2021-05-06-13-19 | 16.2 / 7.1 / 3.5 / 3.8 / 6.5 / 7.5 | 146-238 | 182995-229005 |
| boreas-2021-05-13-16-11 | 2.0 / 7.1 / 1.9 / 2.9 / 1.8 / 14.9 | 127-244 | 192067-228745 |
| boreas-2021-06-03-16-00 | 2.8 / 5.7 / 2.4 / 1.4 / 1.8 / 7.7 | 117-256 | 191468-222128 |
| boreas-2021-06-17-17-52 | 2.1 / 7.2 / 1.5 / 3.5 / 4.8 / 7.3 | 154-233 | 196360-226401 |
| boreas-2021-06-29-18-53 | 5.7 / 23.3 / 15.0 / 10.6 / 17.4 / 15.9 | 165-238 | 185625-216928 |
| boreas-2021-06-29-20-43 | 7.7 / 2.6 / 4.3 / 2.6 / 4.6 / 8.5 | 143-230 | 199662-220118 |
| boreas-2021-07-20-17-33 | 8.2 / 15.1 / 7.3 / 10.4 / 3.2 / 11.6 | 185-252 | 198900-226961 |
| boreas-2021-07-27-14-43 | 5.5 / 6.7 / 4.4 / 1.6 / 2.3 / 3.7 | 172-243 | 199535-221372 |
| boreas-2021-08-05-13-34 | 1.0 / 9.8 / 2.4 / 1.6 / 3.7 / 4.9 | 119-235 | 188263-222343 |
| boreas-2021-09-02-11-42 | 14.3 / 2.0 / 3.1 / 3.8 / 2.5 / 2.8 | 125-232 | 199750-228708 |
| boreas-2021-09-07-09-35 | 8.5 / 7.2 / 4.4 / 6.2 / 3.8 / 2.3 | 163-242 | 183117-227131 |
| boreas-2021-09-08-21-00 | 14.1 / 2.4 / 1.8 / 1.7 / 1.2 / 4.7 | 113-255 | 202633-225275 |
| boreas-2021-09-09-15-28 | 1.9 / 5.7 / 8.9 / 8.8 / 1.5 / 2.5 | 160-249 | 211893-228360 |
| boreas-2021-09-14-20-00 | 1.7 / 0.7 / 2.6 / 5.1 / 2.2 / 4.2 | 132-253 | 202949-220470 |
| boreas-2021-10-05-15-35 | 2.9 / 10.5 / 1.9 / 5.8 / 1.6 / 11.0 | 156-256 | 190222-232168 |
| boreas-2021-10-15-12-35 | 13.1 / 6.0 / 6.1 / 3.1 / 1.6 / 10.0 | 202-247 | 190664-225603 |
| boreas-2021-10-22-11-36 | 13.3 / 2.8 / 2.6 / 4.7 / 4.6 / 10.4 | 142-255 | 206229-225220 |
| boreas-2021-10-26-12-35 | 10.1 / 21.4 / 15.1 / 12.4 / 13.7 / 29.6 | 129-251 | 188402-228416 |
| boreas-2021-11-02-11-16 | 12.5 / 3.5 / 3.0 / 4.3 / 3.1 / 8.4 | 139-235 | 196437-223684 |
| boreas-2021-11-06-18-55 | 3.0 / 6.7 / 2.6 / 2.9 / 2.4 / 16.2 | 163-254 | 195610-222735 |
| boreas-2021-11-14-09-47 | 14.4 / 6.9 / 6.8 / 10.8 / 4.5 / 13.7 | 118-254 | 187557-227526 |
| boreas-2021-11-16-14-10 | 4.2 / 7.9 / 2.8 / 3.0 / 5.0 / 11.5 | 114-254 | 197063-217585 |
| boreas-2021-11-23-14-27 | 4.1 / 7.0 / 3.1 / 2.2 / 3.3 / 9.6 | 108-255 | 192939-223180 |
| boreas-2021-11-28-09-18 | 26.4 / 19.9 / 5.9 / 7.1 / 7.0 / 22.4 | 155-247 | 185877-216568 |

## Files

- `discover.sh`: documents how `sources.tsv` was resolved from live listings.
  It is not part of the acceptance path.
- `download.sh`: fetches the license text and the 264 pinned sweeps. It checks
  size, MD5 and semantics, and it is resumable.
- `build.sh`: runs `scripts/build_samples.py` to write the samples, the
  index, and `build_stats.json`.
- `verify.sh`: runs `scripts/verify_samples.py`, an independent re-decode
  with `struct`. It also checks every payload against `payload_sha256.tsv`.
- `payload_sha256.tsv`: per-sweep SHA-256, recorded from the first download
  on 2026-10-08.
- `scripts/boreas_lidar.py`: listing parser, selection, the shared validation
  policy, and the self-test.
