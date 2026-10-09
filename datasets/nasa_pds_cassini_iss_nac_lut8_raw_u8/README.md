# nasa_pds_cassini_iss_nac_lut8_raw_u8

Raw 8-bit CCD frames from the Cassini Imaging Science Subsystem (ISS)
narrow-angle camera (NAC), taken in the Saturn system from 2008-11-07 to
2009-02-10 (extended mission, revs 92-103). Each sample is one full
1024 × 1024 uint8 frame of uncalibrated data numbers (DN). The camera
converted each 12-bit ADC count to 8 bits on board through its fixed ROM
look-up table (`DATA_CONVERSION_TYPE = TABLE`), and the frame was downlinked
with lossless compression. The values are emitted exactly as transmitted.

## Source

- NASA PDS Imaging Node, data set `CO-S-ISSNA/ISSWA-2-EDR-V1.0`, volumes
  `COISS_2050`, `COISS_2051` and `COISS_2052`:
  `https://planetarydata.jpl.nasa.gov/img/data/cassini/cassini_orbiter/coiss_20NN/`.
- Product: `data/<sclk range>/N<sclk>_<n>.IMG`. This is a VICAR2 file with an
  attached PDS3 detached label (`.LBL`, not fetched; the VICAR label carries
  the same keywords).
- MD5 pins come from the PDS Rings Node checksum manifests of the same volumes
  (`pds-rings.seti.org/holdings/checksums-volumes/COISS_2xxx/COISS_20NN_md5.txt`).
  The probe frame `N1604723153_1.IMG` fetched from the Imaging Node matched
  its Rings Node MD5, and so did all six index files.
- Rights: NASA PDS mission data under the NASA SMD open scientific data
  policy. This is the same basis as the accepted
  `nasa_pds_cassini_vims_qube_i16`, `nasa_pds_cassini_radar_bidr_sigma0_u8`
  and `nasa_pds_voyager_iss_saturn_raw_u8` recipes. The COISS_2050
  `aareadme.txt` has acknowledgments only and no copyright or use
  restriction. `download.sh` fetches it pinned and checks it.

## Selection (`discover.py`, pinned in `sources.tsv`)

The rule lives in `scripts/coiss.py` (`eligible`, `select`). It is applied to
the 10,881 rows of the three volume indexes, in volume order and then row
order (which is chronological). `download.sh` and `build.py` re-derive it
with a fixed-width parser driven by `index.lbl`. `verify.py` re-derives it
independently with `csv` (multi-item columns expanded from `ITEMS`).

Keep rows that meet all of these:

- `INSTRUMENT_ID = ISSNA`, `DATA_CONVERSION_TYPE = TABLE`,
  `INSTRUMENT_MODE_ID = FULL`, `INST_CMPRS_TYPE = LOSSLESS`
- `MISSING_LINES = 0`, `MISSING_PACKET_FLAG = NO`
- `GAIN_MODE_ID = 29 ELECTRONS PER DN`. This drops 28 frames taken at
  12 e/DN, a different DN scale.
- `IMAGE_OBSERVATION_TYPE = SCIENCE`, `PRODUCT_TYPE = EDR`
- `TARGET_NAME != SKY`
- `OBSERVATION_ID` does not contain `SATELLORB`. These 233 frames are
  satellite-orbit astrometry of point-like small moons on dark sky. Three
  probed SATELLORB frames had 75-84% of their pixels at DN 8, and a fourth
  was 61% saturated.

That leaves 2,932 eligible frames in 37 observations. The volumes are
dominated by long F-ring and ring movies (up to 278 frames each, often
near-identical consecutive frames). To avoid duplicate pointings, at most 10
frames are taken per `OBSERVATION_ID`. They sit at evenly spaced positions
`floor((2j+1)·n/(2m))`, `j < m = min(n, 10)`, within each observation's
eligible frames.

Result: **314 pinned frames**, 2008-312T03:52:25 to 2009-041T17:00:16. After
the exclusion rule below, 280 are emitted. The breakdown that follows is for
all 314 pinned frames.

- By volume: 169 from COISS_2050, 10 from COISS_2051, 135 from COISS_2052.
- `TARGET_NAME`: SATURN 231 (ring observations), PROMETHEUS 20 (F-ring
  streamer-channel sequences), MIMAS 18, ENCELADUS 16, TITAN 10, HELENE 9,
  TETHYS 5, RHEA 5.
- Filters: 251 CL1+CL2 (clear). The other 63 use colour, IR, methane-band
  and polarizer filters (IR1 15, GRN 11, IR3 7, BL1 7, RED 4, P60/P0/P120+GRN
  6, UV3 3, CB2 3, CB3 3, MT1-3 4). These change the bandpass but not the
  sensor, LUT or gain regime.
- Exposures run from 60 ms to 46 s.

Every file is 1,077,344 bytes, so the frames total 338,286,016 bytes. The
index files add 33,407,546 bytes and the aareadme 34,646, for a download of
about 371.7 MB.

Not selected:

- **12BIT products.** These are 16-bit, a different width and quantization.
- **LSB-conversion products.** These keep the low 8 bits, a different mapping.
- **SUM2/SUM4 summed modes.** These are 512² or 256² frames with different
  noise.
- **Lossy frames.**
- **The wide-angle camera (ISSWA).** This is a different optical system. It
  could form its own family.

## Decode

Each VICAR label in the probe reads `LBLSIZE=3144 RECSIZE=1048 NL=1024
NS=1024 NBB=24 NLB=1 FORMAT='BYTE' ORG='BSQ' EOL=0`. The decoder parses
every one of these per file and never hardcodes them.

| bytes | content |
|---|---|
| 0 .. LBLSIZE-1 | VICAR label (3 records here) |
| next NLB × RECSIZE | binary telemetry header record (PDS `TELEMETRY_TABLE`) |
| next NL × RECSIZE | 1024 image records: 24-byte binary line prefix + 1024 uint8 DN |

The line prefix (PDS `prefix3.fmt`) holds the line number, valid-pixel
ranges and overclocked-pixel sums. The label sets `BINTFMT='HIGH'`, and the
probe showed that the first two prefix bytes are the 1-based line number
stored big-endian. The decoder asserts this for every line as a check on
alignment. Prefix and header bytes are dropped. The 1024 rows are
concatenated in file order into 1,048,576 bytes.

Probe stats for 23 real frames, 14 of them in the final pinned selection:

- Ring movies: DN 4-233, 150-246 distinct values, mode share 0.08-0.49.
- Titan: mean DN 163.
- Rhea: 250 distinct values.

## Exclusion rule (build and verify, identical)

A frame is not emitted if either of these holds:

- one DN value holds more than 50% of its pixels
- it has fewer than 16 distinct DN values

This targets dark-sky frames with a small target, and overexposed frames.
Of the 14 probed frames that are in the final selection, 2 would be dropped:

- a Helene close-approach frame (80% DN 8)
- an Enceladus frame (53% DN 8)

Realized build: **280 frames emitted, 34 excluded** (293,601,280 bytes,
36 observations). Every exclusion was for mode share > 50% (at DN 8 or 9; the
distinct-value floor never fired). Dropped by observation: Helene close
approach 9 of 9 (whole observation gone), Mimas phase sequence 9 of 10,
Enceladus UVIS ride-along 4, Enceladus geology 3, Tethys geology 2, F-ring
streamer channel 2, F-ring movies 2 + 1 (one at 0.5008), and one frame each
from two radial-ring scans. Excluded frames are listed with their reason in
`filtered/.../ingest_stats.json`.

## How this differs from `nasa_pds_voyager_iss_saturn_raw_u8`

Both are 8-bit raw narrow-angle frames of Saturn, but the sensor and the
quantization differ:

| | Voyager 2 ISS NAC (1981) | Cassini ISS NAC (2008-09) |
|---|---|---|
| detector | selenium-sulfur vidicon tube, 800 × 800 | CCD (front-illuminated, 12 µm pixels), 1024 × 1024 |
| quantization | native 8-bit linear ADC | 12-bit ADC → 8 bits through an on-board square-root-like LUT |
| artifacts | reseau grid, vidicon blemishes, shading, dropout lines | bias/overclock offset, CCD dark current, cosmic rays, antiblooming |
| typical background | DN near 0 | DN ≈ 8-13 (bias plus LUT) |

The LUT changes the noise structure. Shot noise becomes roughly constant in
DN across the range, so the DN histogram and the local-difference statistics
differ from linear vidicon data. The scout's read-only feature probe put
Voyager 0.118-0.188 away from Cassini frames. The nearest library families
were 0.040-0.073 away: `video_chroma_cb_u8` for ring frames, then MIT-BIH and
an HC18 ultrasound set. Ring frames are therefore borderline on features, and
the zlsim gate decides.

## Outputs

- `samples/nasa_pds_cassini_iss_nac_lut8_raw_u8/cassini_issna_table8_full_dn_u8/<product>.u8`:
  1,048,576 uint8 values per frame, 1024 × 1024, row-major
- `index/nasa_pds_cassini_iss_nac_lut8_raw_u8/samples.jsonl`: one row per
  sample with the required fields plus volume, image number, observation id,
  target, filter, exposure, time, min/max, distinct values, mode share and
  SHA-256
- `filtered/nasa_pds_cassini_iss_nac_lut8_raw_u8/ingest_stats.json`: per-frame
  stats, exclusions and the aggregate DN histogram

## Scripts

- `discover.py`: author-time resolution of `sources.tsv`. It uses curl for
  the indexes, the Rings Node MD5 manifests and a HEAD request per frame.
- `download.sh`: fetches the pinned aareadme, indexes and frames. Downloads
  are resumable and checked for size and MD5. Each frame also gets a VICAR
  decode check.
- `build.sh` → `scripts/build.py`: works from local files only and uses
  `scripts/coiss.py`.
- `verify.sh` → `scripts/verify.py`: an independent re-implementation of the
  index parsing, selection, VICAR parsing, decode and exclusion. It
  byte-compares every sample and checks the index rows, totals and manifest.
