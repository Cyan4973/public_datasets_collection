# NOAA NCEI Okeanos Explorer EX1711 Kongsberg EM302 Water-Column Amplitudes (int8)

Native signed-int8 multibeam water-column backscatter amplitudes from the
Kongsberg EM302 on NOAA Ship Okeanos Explorer, cruise EX1711 (2017-11-29 to
2017-12-21). The source is the NOAA NCEI Water-Column Sonar Data Archive
public bucket `s3://noaa-wcsd-pds`. Each sample is one complete ping: all 288
receive beams, each with its Ns int8 amplitudes (0.5 dB steps, TVG applied by
the system, -128 = floor code), concatenated in beam order.

## Source and license

- Bucket listing: `https://noaa-wcsd-pds.s3.amazonaws.com/?list-type=2&prefix=data/raw/Okeanos_Explorer/EX1711/EM302/`
  (407 `.wcd` files, 92.6 GB, uploaded 2021-03-06).
- License: the AWS Open Data registry entry
  (`awslabs/open-data-registry/datasets/ncei-wcsd-archive.yaml`) says:
  "The data may be used and redistributed for free but is not intended for
  legal use, since it may contain inaccuracies." The data are U.S. Government
  (NOAA) observations.
- Citation (from the cruise README): NOAA Office of Ocean Exploration and
  Research (2017): Water Column Sonar Data Collection (EX1711, EM302).
  National Centers for Environmental Information, NOAA. doi:10.7289/V5W957HS.

## Bounded subset

The recipe takes 15 whole files, 357,457,606 bytes in total. They are spread
over the cruise from 2017-11-30 to 2017-12-20, roughly one per survey day or
segment, and cover all three depth modes seen in the cruise. Small, complete
files were preferred over parts of large ones. Every object is pinned by size
and S3 ETag; the table is in `scripts/em302_wcd.py` (`FILES`) and in the
manifest. The bucket has no checksum manifest. ETags ending in `-N` are S3
multipart ETags over 8 MiB parts (MD5 of the part MD5s), and
`download.sh` recomputes them locally.

File 0109 was probed and left out because its first pings are blank (no
detections, every amplitude -128). File 0062 was pinned at first but dropped
after the first download. Its archived object (10,977,280 bytes, exactly
2680 x 4096) matches its S3 ETag but ends inside a truncated water-column
datagram, so it fails framing validation. 0064 replaces it: same day, same
depth mode, and the datagram chain ends exactly at EOF. Tail probes of all 15
selected files confirm clean termination with the closing `i` datagram. Files adjacent to selected ones were
skipped to favour spread over volume.

## Decode

The `.wcd` file is a stream of Kongsberg EM datagrams:
`[u32 length][STX 0x02][type][u16 model]...[ETX 0x03][u16 checksum]`. The
checksum is the 16-bit sum of the bytes strictly between STX and ETX. Every
datagram in every file must pass the length, STX, ETX, checksum and
model == 302 checks; any failure rejects the file in download, build and
verify.

For a water-column datagram `k` (0x6B), the fields after the common header
are: Nd, datagram number, Ntx, Nrx-total, Nrx, sound speed, sample frequency
(0.01 Hz), TX heave, TVG function X, TVG offset C, scan info and 3 spare
bytes. Then come Ntx 6-byte transmit-sector entries, then Nrx beams of
`{i16 pointing angle, u16 start range sample, u16 Ns, u16 detected range,
u8 tx sector, u8 beam number}` each followed by Ns int8 amplitudes, then an
optional zero spare byte.

Datagrams are grouped by (date, time, ping counter). A ping is emitted only
when all of datagrams 1..Nd are present, they agree on every per-ping header
field, the beam total is 288 and pointing angles strictly decrease (beam
order). The beam-number byte is always 255 in this EM302 firmware, so beam
order is checked through the pointing angles instead.

## Policies

- `-128` is the native floor code and is kept.
- A partial ping is dropped only when it is the first or last water-column
  ping of a file (logging started or stopped mid-ping). A partial ping
  anywhere else is fatal.
- Blank pings (every amplitude identical) are dropped and counted in
  `filtered/<id>/ingest_stats.json`.
- The following are fatal: system serial other than 101, TVG function other
  than 30, TVG offset other than 20 dB, Nrx-total other than 288, a non-zero
  start range sample, an out-of-range sector, inconsistent per-ping headers,
  decreasing timestamps, and duplicate ping payloads.

## Homogeneity notes

All samples come from one EM302 (serial 101), one vessel and one cruise, with
one TVG law (X = 30, C = 20 dB) and the same 0.5 dB int8 lattice. The EM302
switches depth mode automatically. Across the selected files the water-column
sample frequency is 202.92, 295.16 or 541.13 Hz, with 4, 6 or 8 transmit
sectors. This changes range resolution and swath geometry, so ping sizes
range from 86,916 to 549,808 values, but not the quantity or its scale. The
card's "8 TX sectors" holds only for some modes: files 0043 and 0064, for
example, use a 4-sector mode at 541.13 Hz. Per-ping mode fields are kept in
the index (`sample_frequency_hz`, `tx_sector_count`,
`water_column_datagram_count`).

## Realized output (build of 2026-10-05)

- 1,953 complete pings from 15 files, covering 14 calendar days between
  2017-11-30 and 2017-12-20. Pings per file range from 26 to 348.
- Primary: 343,505,942 int8 values (343.5 MB). Values per ping: median
  115,350, range 86,916 to 549,808.
- Modes (pings): 1,164 at 202.92 Hz with 8 sectors, 428 at 295.16 Hz with 8
  sectors, 123 at 295.16 Hz with 6 sectors, and 238 at 541.13 Hz with 4
  sectors.
- No ping was dropped: 0 edge-partial and 0 blank. All 1,953 pings have
  TVG 30/20.
- Amplitudes span -128 to +127. The floor code -128 is 0.67% of all values
  (at most 11% in any one ping), and only 15 pings reach +127. Each ping has
  169 to 255 distinct levels (median 193). zlib -9 on 40 random pings gives a
  ratio of 0.80 to 0.86.
- Auxiliary: 2 x 1,953 samples of 288 values each (1,124,928 bytes per
  series).

## Output

- Primary: `samples/<id>/em302_ping_water_column_amplitude_i8/<file>_pingNNNN_pcNNNNN.bin`,
  raw int8 holding the beams concatenated in order.
- Auxiliary (alignment only, not counted toward floors):
  `em302_ping_beam_sample_count_u16` (288 per-beam Ns values, which locate
  the beam boundaries in the primary vector) and
  `em302_ping_beam_pointing_angle_i16` (288 angles in 0.01 degree).
- Index rows: `index/<id>/samples.jsonl`. Primary rows carry the source file,
  datagram offsets, ping counter, date and time, mode fields, stored-int8
  min/max, floor count, distinct-value count and sha256.

Excluded: the EK60 folder of the same cruise, all other cruises and sonar
models, and the auxiliary datagrams (P, A, H, R, I, U), which are
framing-checked only.

## Scripts

- `download.sh`: checks the live S3 listing against the pins, fetches the
  cruise README and the 15 files (resumable `curl -C -` into `.part`), checks
  size and ETag, runs a full datagram scan, then renames.
- `build.sh`: `scripts/em302_wcd.py build`, using local files only.
- `verify.sh`: `scripts/verify_em302.py`, an independent streaming re-decoder
  that compares every sample byte for byte. It also checks index metadata,
  stored-int8 min/max, hashes, dropped-ping accounting and manifest totals,
  and rejects degenerate pings (fewer than 16 distinct values).
