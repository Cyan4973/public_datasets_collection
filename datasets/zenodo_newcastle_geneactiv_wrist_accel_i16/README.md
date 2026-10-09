# Newcastle PSG+Accelerometer 2015: GENEActiv left-wrist raw accelerometer counts (int16)

Raw tri-axial wrist accelerometry from the Newcastle polysomnography and
accelerometer study 2015 (van Hees, Charman, Anderson; Zenodo record 1160410,
DOI 10.5281/zenodo.1160410). Sleep-clinic patients wore one GENEActiv
accelerometer on each wrist through one polysomnography night. The devices
recorded at 85.7 Hz with a range of +/-8 g. Each sample word stores x, y and z
as 12-bit two's-complement ADC counts (about 256 counts per g, uncalibrated).

This recipe emits **one sample per complete left-wrist device recording**: the
stored x, y, z counts of every page, sign-extended to int16 and interleaved
per frame (`x0 y0 z0 x1 y1 z1 ...`, little-endian).

## Source and license

- Record: <https://zenodo.org/records/1160410>, version 1.0, published
  2018-01-25. One file, `dataset_psgnewcastle2015_v1.0.zip`: 962,798,652
  bytes, md5 `8ebadbc55cb0e76230f293fc6d53f504`.
- License: **CC BY 4.0**. The record API reports
  `"license": {"id": "cc-by-4.0"}` and `"access_right": "open"`.
  `download.sh` re-checks the license, access right, DOI, file size and md5
  on every run.
- Protocol paper: van Hees et al. (2015), PLoS ONE 10(11): e0142533,
  <https://doi.org/10.1371/journal.pone.0142533>.

## Privacy handling

The GENEActiv file headers in the deposit contain subject fields. The authors
published them openly, but this recipe does not use them:

- Headers are parsed in memory only. The recipe asserts device type
  `GENEActiv`, `Measurement Frequency` `85.7 Hz`, `Accelerometer Range`
  `-8 to 8` and `Number of Pages`, then discards the header. No header value is
  printed, logged, indexed or written to disk.
- `participants_info.csv` and the PSG sleep-score `.txt` files are never
  requested. Only the central directory and the 13 member spans are
  range-fetched.
- Per-page metadata (page time, temperature, battery) and the light and button
  bits are validated or ignored, never emitted.

## Scope and selection

The ZIP has 55 `.bin` members: 28 left wrist and 27 right wrist (the right
wrist of participant 10 is missing). To collect one body side and stay well
under the cap, the recipe applies this rule. `scripts/geneactiv.py check-cd`
re-derives it from the live central directory on every run, and the result is
pinned in `members.tsv`:

1. Take the left-wrist members.
2. Keep those with an uncompressed size of at most 100 MB. This keeps 26 and
   drops the multi-day MECSLEEP23 and MECSLEEP34 files.
3. Order by participant number and take every second one, starting with the
   first.

The result is 13 recordings: participants 01, 10, 17, 27, 29, 32, 38, 42, 48,
50, 52, 56 and 59. They were recorded from June 2013 to May 2015 on at least
ten different devices. Three are 12 h sessions (47 MB of hex each). The rest
are 15 h to 24 h sessions (68-94 MB of hex). The download is 194,859,344
bytes of member spans, which inflate to 989,856,562 bytes of hex text. The
expected output is about 467 MB (1,800 bytes per 300-sample page).

The recordings include whatever the device logged during the session, so
pre-wear, off-wrist and post-wear stretches stay in. A page counts as
quasi-static when every axis has a standard deviation of at most 3.3 counts
(13 mg, the GGIR non-wear threshold). The test is exact integer arithmetic.
The sensor noise floor alone gives axis spans of 10-18 counts within one
page, so even a still device is never literally flat. A recording fails if
more than half of its pages lie in quasi-static runs of 60 min or longer
(non-wear-like). It also fails if one code holds more than 50% of its values,
if it has fewer than 256 distinct codes, or if any axis is constant.

Realized output (2026-10-08):

| | |
| --- | --- |
| samples | 13 |
| values | 233,424,900 |
| bytes | 466,849,800 |
| pages per recording | 12,336-24,672 (3.70-7.40 M frames) |
| distinct codes per recording | 1,080-1,437 |
| mode share | 0.9-2.6% |
| full-scale (clipped) codes | 0-37 per recording |
| quasi-static pages | 83-92% (mostly sleep) |
| pages in quasi-static runs of 60 min or more | 0-24.8% |
| longest quasi-static run | 2.87 h (MECSLEEP38) |

## Format and decode

A GENEActiv `.bin` file is CRLF text. A header block (Device Identity,
Capabilities, Configuration, Trial/Subject Info, Calibration Data, Memory
Status) is followed by `Number of Pages` pages. Each page has these lines:

```
Recorded Data
Device Unique Serial Code:...
Sequence Number:<page index>
Page Time:...
Unassigned:
Temperature:...
Battery voltage:...
Device Status:...
Measurement Frequency:85.7
<3,600 hex characters = 300 x 48-bit words>
```

For each 48-bit word `w`, bits 47-36 are x, 35-24 are y and 23-12 are z, all
12-bit two's complement. Bits 11-2 are light, bit 1 is the button and bit 0 is
reserved. The emitted values are
`x = sext12((w >> 36) & 0xFFF)`, and likewise y (shift 24) and z (shift 12).
The first frame of MECSLEEP01 decodes as `(-13, 248, -106)`.

## Pipeline

1. `download.sh` checks the record JSON. It re-reads the central directory and
   EOCD (last 10,396 bytes) and re-derives `members.tsv`. Then it range-fetches
   each member span `[local header, next local header)` with manual-offset
   resume and a 206 + exact `Content-Range` check per chunk. Each span is
   fully inflated (raw DEFLATE) and checked for CRC32, size and the complete
   page structure before it is kept.
2. `build.sh` runs the synthetic self-test, re-checks the central directory,
   and decodes each span with the fast decoder (unhexlify, byte-lane slicing,
   16-bit lookup tables). It writes
   `samples/<id>/geneactiv_wrist_accel_xyz_i16/<sample_id>.bin`,
   `index/<id>/samples.jsonl` and `filtered/<id>/ingest_stats.json`.
3. `verify.sh` re-decodes every page with an independent per-word integer
   decoder and compares the bytes page by page. It then recomputes the index
   fields (sha256, min/max, distinct codes, mode share, axis ranges, static
   fraction) and checks the degeneracy rules, the floors, the 1 GB cap and the
   manifest totals.

Any structural error is fatal: wrong header frequency, range or device type, a
page count that differs from the header, a sequence gap, a wrong page
frequency, a data line that is not 3,600 hex characters, or a CRC/size
mismatch. No page is skipped or repaired.

## Notes and caveats

- The signal is mostly sleep, so long low-motion stretches dominate. Values
  sit near the gravity component of each axis, with bursts of movement.
- Only 12 of the 16 bits are used (range -2048..2047). This is the native ADC
  width; int16 is the natural container.
- Per-device calibration (the gain and offset in each file's header) is not
  applied, so scale and offset differ slightly between devices (nominally
  about 256 counts per g). Header values are never read out or stored.
