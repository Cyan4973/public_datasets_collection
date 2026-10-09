# EarthScope PBO Gladwin tensor borehole strainmeter gauge counts (int32)

Raw 1-sps gauge counts from the four horizontal extensometer gauges (LS1-LS4)
of Plate Boundary Observatory Gladwin tensor borehole strainmeters, FDSN network
`PB`, location `T0`. Each sample is one complete gauge-channel UTC day: 86,400
little-endian int32 counts (345,600 bytes).

## Source and license

- EarthScope FDSN web services (`service.earthscope.org/fdsnws`; the old
  `service.iris.edu` host 307-redirects there). `dataselect` returns Steim2
  miniSEED 2 (512-byte records, blockette 1000 encoding 11, big-endian);
  `station` gives the channel inventory. The FDSN availability service is
  retired (HTTP 410), so completeness is decided from the decoded records.
- License: CC BY 4.0. The GAGE Facility Data License page says all data from
  EarthScope-operated facilities are licensed under CC BY 4.0. PBO
  strainmeters were run by UNAVCO (now the EarthScope Consortium) for NSF
  EarthScope/GAGE. `download.sh` re-fetches the page and checks for the
  statement.

## Query plan

`plan.tsv` lists 154 (station, UTC day) rows: 77 Gladwin stations x 2 days,
covering 2008-2024. It was resolved once by `discover.sh`
(`scripts/discover.py`), as follows:

1. Station inventory of PB `LS?` channels. Keep location `T0`, 1 sps, and
   sensor "GLADWIN TENSOR STRAINMETER*". The `LM` laser strainmeters share
   the `LS?` codes but are a different instrument, so they are excluded.
2. For each station and each year 2008-2024 inside the channel epoch, take
   one candidate day. The month and day come from `crc32(station:year)`. Days
   in the first 90 days after installation are skipped.
3. Run a 2-minute LS1 presence probe at 00:00 and 23:58 of every candidate
   (chunked POSTs). Result: 1,200 of 1,268 candidates were present.
4. Per station, pick two present years half the list apart, with the pick
   rotated by station index so the plan covers every year.

`download.sh` makes one GET per row for `cha=LS1,LS2,LS3,LS4`, about 300 KB per
station-day and about 46 MB in total. It then decodes everything, checking
stream identity, Steim2 encoding, X0/Xn integration constants and the inventory
instrument class. It writes `download_outcome.tsv` (status of each gauge-day)
and `mseed.sha256`. It fails if there are fewer than 300 complete gauge-days.

## Conversion

`scripts/mseed.py` is a pure-stdlib miniSEED 2 reader:

- detects header byte order from BTIME
- reads record length, encoding and word order from blockette 1000, and the
  microsecond offset from blockette 1001
- applies the header time correction
- decodes Steim1/Steim2, checking every record's last sample against Xn

It was self-tested on a synthetic independent Steim2 encoder (all seven
difference widths, 512- and 4096-byte records, both header byte orders,
duplicate/gap/corrupted-Xn cases) and on a real B004 LS1 day.

A gauge-day is emitted only when all of these hold:

- all 86,400 one-second slots are filled exactly once (identical duplicates
  are tolerated)
- it is on the 1-s lattice
- it has at most 1% `999999` fill
- it has at least 16 distinct non-fill values

Otherwise the whole day is skipped and logged in `ingest_stats.json`. Days are
never split, spliced or concatenated.

## Realized output (build of 2026-10-08)

- Download: 154 station-days, 47.5 MB.
- Output: 608 complete gauge-days from 77 stations, covering 2008-2024
  (52,531,200 values, 210,124,800 bytes).
- Skipped gauge-days, 8 in total (listed in `ingest_stats.json`):
  - 5 with a single missing second: B012 2024-12-05 LS1-LS4 and B081
    2024-03-12 LS2
  - 2 with no data: B011 2019-12-01 LS2 and B950 2019-07-21 LS4
  - 1 that is 90% fill: B935 2020-01-15 LS1

## Known source behaviour (kept, not filtered)

- **`999999` fill**: PBO raw gauge streams carry an in-stream `999999` value,
  typically once per hour. B004 2015-06-20 has 24, at hh:30:21. It is
  preserved verbatim and counted per sample (`fill_999999_count`).
  Across the realized output:
  - 121 samples have no fill
  - most samples have 23-27 fill values (hourly)
  - 112 samples have 30-594 fill values, because short telemetry or logger
    outages are also written as contiguous 999999 runs (for example 594 s on
    B010 2022-10-14, on all four gauges)
  - the 1% cap (864) is never reached in emitted samples
- **Large DC offsets**: these differ per gauge (B004 LS1 is about 4.7e7),
  so the upper bytes are used.
- **Gauge resets and steps**: re-zeroing events and offsets occur. They are
  real instrument behaviour, and `max_abs_step` in the index documents them.
  - Median max |step| between non-fill neighbours is 26 counts; the 99th
    percentile is about 3.3e5.
  - 14 samples have steps above 1e5 counts. Examples: B010 LS3 2022-10-14
    1.9e6, B082 LS1 2016-04-28 1.8e6, B076 LS1 2021-01-03 2.7e6.
  - One sample (B072 LS2 2023-07-06) contains a single `-1` value next to a
    fill run, which is a logger glitch preserved as-is.
- **Gauge ranges**: per-sample non-fill minima span 1.4e7..9.7e7 (1st-99th
  percentile 3.6e7..6.1e7; median 5.0e7), apart from the single -1 glitch.
  The median daily range is about 1,100 counts. No sample fits in 16 bits.

## Files

- `plan.tsv`: pinned station-day plan
- `discover.sh`, `scripts/discover.py`: how the plan was resolved
- `scripts/mseed.py`: miniSEED/Steim2 decoder
- `scripts/strain.py`: `validate` / `build` / `verify`
