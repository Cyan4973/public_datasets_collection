# usgs_grandbay_klein3900_sidescan_xtf_u16

Raw side-scan sonar backscatter from the USGS 2015 Grand Bay (Mississippi and
Alabama) survey: **24 complete Klein SonarPro XTF recording files**, each
emitted as one ping-major little-endian `uint16` array of shape
`[pings, 2, 4096]` (port channel, then starboard channel, 4096 slant-range
samples each, in stored order). The port samples run far range → nadir and
the starboard samples run nadir → far range, so each ping row is one
continuous across-track line: port-far, through nadir, to starboard-far.

- Source: Locker, S.D., Forde, A.S., and Smith, C.G., 2018, *Subbottom and
  sidescan sonar data acquired in 2015 from Grand Bay, Mississippi and
  Alabama*, U.S. Geological Survey data release,
  <https://doi.org/10.5066/P9374DKQ>. Landing page:
  <https://coastal.er.usgs.gov/data-release/doi-P9374DKQ/>.
- License: U.S. Government public domain. The FGDC metadata says:
  "Access_Constraints: None. These data are held in the public domain.
  Use_Constraints: Public domain data from the U.S. Government are freely
  redistributable with proper metadata and source attribution." The usgs.gov
  catalog page for the release is marked CC0 1.0. `download.sh` re-checks
  these phrases against the pinned metadata SHA-256.

## Material

The towfish was towed by the 17-ft catamaran *RV Jabba Jaw* (USGS project
15CCT03), 2015-05-28 to 2015-06-03. The sonar was recorded with Klein
SonarPro 12.1 in Triton XTF. Each XTF file is one SonarPro recording file. A
file rolls over at about 13,400 pings (about 30 minutes at 0.1333 s per ping),
and shorter files are short lines or line ends. Every one of the 143 files
has the same byte layout: a 1,024-byte XTF file header, then N repetitions of
one 832-byte HeaderType-108 Klein auxiliary record and one 16,768-byte
HeaderType-0 sonar ping. A sonar ping is a 256-byte ping header plus, for
each of 2 channels, a 64-byte channel header followed by 4096 × uint16
samples.

From the afternoon of 2015-06-02 onwards, files carry a Julian-day prefix
(`15CCT03_SSS_153_…`, `15CCT03_SSS_154_…`). Their file header (program,
sonar name, CHANINFO) and ping configuration are identical to the
date-only names, as checked on all 143 members' leading pings. 11 of the 24
selected files are of this kind.

The emitted values are the raw uint16 sample arrays: unscaled echo amplitude
counts with 12–13 effective bits (0 to 4,685 in the realized output). They
are copied in stored order and never reordered.

Orientation, from medians over all pings (my author-phase note said both
channels were nadir-first; that was wrong):

- **Port** is stored far → near. `port[0:7]` is zero padding. A flat
  noise floor (about 45 counts) follows at about 100 m slant range. Seafloor
  returns rise toward the end of the array. There is a water-column gap
  around `port[4074:4080]`, then the transmit spike around
  `port[4082:4088]` (about 70–375 counts), and nadir at `port[4095]`.
- **Starboard** is stored near → far. It starts at nadir with the water
  column (values 0–2 up to about `stbd[16]`). The first seafloor return
  follows around `stbd[64:512]`, then decay to about 30 counts, then 7
  samples of zero padding at `stbd[4089:4096]`.
- The 7-sample far-range padding (`port[0:7]` and `stbd[4089:4096]`) is
  zero in every one of the 47,882 pings. It is 14/8192 = 0.17% of values,
  is kept verbatim, and `verify.sh` fails if any ping deviates.

Ping headers, channel headers (navigation, timing, gain), and the 108 records
are not emitted. The 108 records hold Klein navigation and status fields:
for example, float64 latitude/longitude in radians that decode to about
30.388°N, 88.388°W. They contain no sonar sample arrays.

### Instrument naming discrepancy

- The FGDC metadata and the equipment log say *Klein System 3900*, dual
  frequency 455/900 kHz, with "the 455 kHz frequency data … utilized".
- The XTF file headers say `SonarName = "Klein 3000"` and
  `RecordingProgramName = "KleinXlt" 4.0`, with a note of `SonarPro 12`.
  Every ping's channel header has a `Frequency` field of `100`, except in the
  first three files of 2015-05-28, where it is `500`.

The Klein 3000 is a 100/500 kHz system, so the 100/500 codes most likely mean
"low band" and "high band" of a towfish that SonarPro identified as a 3000.
Under that reading, the 100-coded files are the 3900's 455 kHz data. This is
an interpretation; the release does not document it. The recipe does not
rely on it. It selects strictly on the header values: frequency field 100,
slant range 100 m, 4096 samples, 2 channels. The frequency-500 files have a
very different amplitude distribution (median about 1,500 against 13–170 for
frequency-100 files) and are excluded.

## Selection rule

The full archive is 9.84 GB and holds 18.2 GB of XTF, far above the 1 GB
primary cap. Full 30-minute files hold about 220 MB of primary data each, so
the cap would allow only four of them. The recipe instead takes every
homogeneous recording file within a duration band:

1. From the ZIP central directory, compute the ping count of each `.xtf`
   member as `N = (uncompressed_size − 1024) / 17600`. This is exact for all
   143 members.
2. Keep files with `1000 <= N < 2700`, which is about 2.2–6.0 minutes of
   towing. That gives 25 members.
3. Drop any member whose first pings are not in the majority configuration.
   This drops one member, `15CCT03_SSS_150528180500.xtf` (frequency field
   500), leaving 24.

The result is pinned in `sources.tsv`: ZIP local-header offset, exact range
end (the next member's local header minus 1), compressed and uncompressed
sizes, CRC32, ping count, and survey date. `discover.sh` is optional and only
documents the selection; it re-derives the table from the live archive
(about 4 MB of probes). The 24 files cover 6 of the 7 survey days (none from
2015-05-30, whose files are all long), with 1,005–2,697 pings each: 47,882
pings in total.

Bias to note: the band favours shorter recordings (line ends after a
rollover, short lines) over full 30-minute segments. Acquisition settings
are identical for every kept ping.

## Scripts

- `download.sh`: verifies the FGDC metadata (SHA-256 and license phrases).
  It then fetches the archive's last 65,536 bytes, checks the total size,
  the ZIP64 EOCD, the central-directory SHA-256, and every pinned member
  entry. Each member is range-fetched as exactly
  `[local header, next local header)`. Resume is manual, because
  `curl --range` combined with `--continue-at -` turns into an open-ended
  request for the whole archive: each attempt asks for
  `[start + held, end]`, checks the 206 `Content-Range`, and appends.
  `--max-filesize` refuses any oversized response. Each member's local
  header and DEFLATE stream are then validated (size and CRC32, ending
  exactly at the member boundary), inflated to
  `downloads/<id>/xtf/<member>.xtf`, and the compressed range is deleted.
  About 464 MB is transferred and about 843 MB stays on disk.
- `build.sh`: `scripts/xtf_sidescan.py build`. It walks the packets by
  `NumBytesThisRecord` and asserts `0xFACE` at every step. It checks the
  file header (FileFormat 0x7B, 2 sonar channels, CHANINFO types 1/2,
  BytesPerSample 2) and checks every sonar ping: 2 channels in order 0,1;
  NumSamples 4096; frequency field 100; slant range 100 m; record length
  equal to `256 + Σ(64 + 2·NumSamples)` rounded up to 64. It fails on any
  deviation, on a ping-count mismatch, or on a degenerate channel (all zero,
  more than 50% zeros, or fewer than 64 distinct values). It writes the
  samples, `index/<id>/samples.jsonl` (min/max computed from the stored
  uint16 values, sha256, ping range and times), and
  `filtered/<id>/build_stats.json`.
- `verify.sh`: `scripts/verify_xtf_sidescan.py`, an independent parser that
  does not import the build helper. It recomputes each member's CRC32,
  re-walks the packets, re-derives the payload and byte-compares it with the
  sample. It also recomputes min/max/value_count/sha256 from the stored
  bytes, applies the same per-channel degeneracy rule, checks that
  `port[0:7]` and `stbd[4089:4096]` are zero in every ping (this pins the
  documented orientation), and checks for
  duplicate payloads, the one-to-one index/source/sample-file mapping,
  manifest totals, the cap, and the floors.

## Realized output (build of 2026-10-06)

| | |
|---|---|
| samples | 24 (one per XTF recording file) |
| pings | 47,882 (1,005–2,697 per file; ping numbers contiguous in every file, 0.1333 s per ping) |
| values | 392,249,344 uint16 |
| primary bytes | 784,498,688 |
| median sample | 2,148.5 pings → 17,600,512 values |
| per-file range | min 0, max 4,359–4,685, 3,753–4,508 distinct values |
| zero fraction | 0.25%–2.7% per file, except `15CCT03_SSS_150528222700` at 10.3%; 0.17% of every file is the structural 7+7-sample far-range padding |

The 10.3% zeros in `15CCT03_SSS_150528222700` are concentrated in the last
third of the recording. Spatially they sit at about 12–62 m slant range on
both sides (port indices about 1536–3583, starboard about 512–2559), where
mean counts are about 20–40. No ping row is all zero. This reads as weak natural
backscatter, not a dropout, so the file is kept. Every one of the 47,882 pings
passed the full configuration check: frequency field 100, slant range 100 m,
4096 samples, 2 channels.
