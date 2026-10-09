# NOAA ASOS One-Minute Page-1 (DSI 6405) Wind Speed UInt8

1-minute wind speed in whole knots from the U.S. Automated Surface Observing
System (ASOS), NCEI data set DSI 6405 ("1-minute page 1"). Two primary uint8
series are produced from each station-month file:

| series | source field | unit |
| --- | --- | --- |
| `wind_speed_2min_avg_kt_u8` | speed of the 2-minute average wind | knots |
| `wind_speed_5s_peak_kt_u8` | speed of the maximum 5-second wind in the minute | knots |

Wind directions (0-360 degrees, so not native u8), visibility extinction
coefficients and runway visual range are not emitted.

## Scope

- 30 open-exposure airport stations, spread across the Plains, Mountain West,
  Great Lakes, Gulf, Atlantic, New England and Pacific Northwest:
  KABQ KABR KBIS KBOS KBTV KCLE KCPR KDDC KDEN KDSM KFAR KGLD KGRI KHON KIAH
  KJAX KJFK KLBF KMIA KMKE KMOT KMSY KORD KPHL KPWM KRAP KSEA KSLC KSTL KSUX.
  Each station has all 12 monthly 2024 files, and none of them is under
  2.29 MB, so there are no long outages.
- Months 2024-01 to 2024-12. That makes 360 station-month files and
  1,580,854,971 bytes downloaded, pinned in `sources.tsv`.
- Natural record: one station-month `.dat` file. One sample per station-month
  per series gives 720 samples of up to 44,640 values each, about 15.5 M
  values per series.

`discover.sh` regenerates `sources.tsv` from the twelve directory listings. It
fetches listings only. Run it only if NCEI republishes files, which makes the
pinned sizes stop matching.

## Format and decoding

DSI 6405 files are fixed-width ASCII with 112 characters plus LF per line
(documentation: `doc/asos-1min-pg1_documentation.pdf`, 2022-11-08). Example:

```
94846KORD ORD2024070100000600    0.105  N                  0.091  N     37    6   40    8   10L60+
```

Columns, as 0-based slices: WBAN `[0:5]`, ICAO `[5:9]`, LST date and time
`[13:25]`, UTC time `[25:29]`, the two extinction coefficients with D/N flags
`[29:69]`, then four 5-character wind fields: 2-min direction `[69:74]`, 2-min
speed `[74:79]`, 5-s peak direction `[79:84]` and 5-s peak speed `[84:89]`.
Each wind field is right-justified digits, `M`, or blank.

When the second visibility sensor is missing, its columns are blank but the
wind columns do not move. The probe below confirmed this, so the fields are
read from fixed columns rather than by splitting on whitespace.

A row counts as structural when all of these hold:
- it is printable ASCII and at least 89 characters long;
- it starts with a 5-digit WBAN and the expected ICAO;
- it has 16 timestamp digits whose LST year and month match the file;
- each of the four wind fields is right-justified 1-3 digits, `   M ` (the
  missing marker always sits at offset 3 of the field) or blank. A wind group
  wrapped in square brackets (`[342    8  339    9]`) fails this check.
  The brackets are undocumented. They also wrap visibility values such as
  `[-1.000]` and `[   M  ]`, so they look like a sensor flag, and the rows are
  dropped rather than guessed at;
- the visibility region `[29:69]`, with brackets ignored, is 0-3 pairs of
  extinction value (`-?d+.ddd` or `M`) and a one-letter flag;
- the tail `[89:]` is blank, `M`, or a single runway group (`35L60+`,
  `31 55`, `04RFFF`).

The last two rules were added in the build phase. Some 2024 files contain
garbled transmissions with inserted or moved characters, for example KRAP
2024-01 (`1 0.0  N ... 298    81`), KPHL 2024-12, KPWM 2024-12, and single
rows at KGLD and KDSM. In these rows the wind digits still parse but come
from the wrong columns. Examples are a 163-knot "gust" that is really a
direction, and an 81-knot gust that is really 8 knots plus a stray `1`.

Rows that fail any check are dropped for both series and counted.

Some files also contain two different records for the same LST minute. Whole
blocks of up to a day appear twice with different wind values, for example
KGRI 2024-01, where 12 kt and 4 kt records alternate. Neither copy can be
preferred, so every row whose LST minute appears more than once in the file
is dropped.

Within the remaining rows, an `M` or blank speed is dropped for that series
only, and nothing is imputed. Values are written as uint8 in file (time)
order. A sample is therefore the sequence of valid minutes, not a
gap-filled lattice.

`verify.sh` re-parses every file with an independent full-line regex and checks:
- sample bytes and sha256 against its own parse;
- the index fields, ingest counts and manifest totals;
- that no sample has fewer than 1,000 values, fewer than 3 distinct values,
  or a single value covering 80% or more of it.

## Probe evidence (2026-10-09, range requests only)

I took 300 KB range slices of 10 station-months (KABQ-06, KBOS-01, KBTV-10,
KCPR-02, KDDC-03, KHON-05, KIAH-09, KMIA-08, KSEA-11, KSLC-12) plus the first
400 KB of KORD-07:
- All lines were 112 characters, and the wind fields sat at columns 71-73,
  77-78, 81-83 and 87-88 in every file.
- `M` was always at column 72, 77, 82 or 87.
- Missing values (`M`) made up 0.2-1.1% of rows.
- The share of the most common value was 0.08-0.23 for average speed and
  0.07-0.20 for gust. Calm minutes do not dominate at these stations.
- The build and verify parsers agreed byte-for-byte on all probes and on a
  synthetic edge-case file: 3-digit gusts, `M`, blanks, missing visibility, a
  malformed field, another month, another station, and control or non-ASCII
  bytes.

## Realized build (2026-10-09)

| | count |
| --- | --- |
| rows read | 13,989,867 |
| rows with a malformed or bracketed wind field | 7,674 |
| rows with a garbled visibility region | 2,214 |
| rows with a garbled RVR tail | 13 |
| rows of a duplicated LST minute | 19,220 |
| rows kept | 13,960,746 |
| 2-min average values (`M` or blank: 126,691) | 13,834,055 |
| 5-s peak values (`M` or blank: 97,525) | 13,863,221 |

- 360 samples per series, 720 in total, 27,697,276 bytes.
- 2-min average: values 0-54 kt. The most common value covers at most 0.208
  of a sample (median 0.101).
- 5-s peak: values 0-73 kt. The most common value covers at most 0.158 of a
  sample (median 0.078).
- After the stricter rules, no value exceeds 255 and timestamps never go
  backwards.
- `verify.sh` reproduces every byte and count independently.

## License

These are federal works of NWS, FAA, DoD and NCEI (17 U.S.C. 105). The NCEI ISO
record `gov.noaa.ncdc:C00386` contains only a citation request ("Cite as: NOAA
National Weather Service, U.S. Federal Aviation Administration, U.S.
Department of Defense, NOAA National Centers for Environmental Information
(2005): 1-Minute Page 1 Surface Weather Observations from the Automated
Surface Observing Systems (ASOS) Network ... NCEI DSI 6405_02") and the
distribution and use liability disclaimers. It sets no use restriction.
`download.sh` saves the record and checks its text.

## Novelty and caveats

- The local corpus has wind only as GHCN-Daily daily AWND/WSFG (16-bit) and
  hourly ISD-lite / NDBC / GSOD wind (16-bit or float). Nothing local or
  downstream has minute-cadence wind speed at 8 bits.
- `noaa_asos_1min_pg2_temperature_dewpoint_i8` is a sibling candidate from the
  same NCEI ASOS one-minute program. It is a different DSI product, file set,
  sensor and quantity.
- Extraction ratio: about 2 bytes kept per 113-byte line, so 27.7 MB of
  primary data from 1.58 GB downloaded. No leaner source of minute data exists
  (IEM's ASOS 1-min service is a third-party re-serve).
- Build-phase `zlsim.py gate` result: verdict OK, and neither series is
  redundant.
  - The nearest neighbour of both series is `lora24_rssi_i8`, locally and
    downstream. It sits at feature distance 0.0626 (average speed) and 0.0625
    (gust), with compression loss 0.0. The redundancy threshold is a distance
    of 0.05.
  - Next nearest are `power_hvac` and `ena_fastq_phred_u8` (distance 0.071,
    loss 0.29 and 0.41).
  - Own compression ratio: average 4.61x, gust 3.07x.
  - Both series are therefore kept. Both are compression-equivalent to the
    LoRa RSSI family and sit only moderately far from it in features.
