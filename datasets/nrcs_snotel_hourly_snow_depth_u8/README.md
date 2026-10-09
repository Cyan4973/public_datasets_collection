# nrcs_snotel_hourly_snow_depth_u8

Hourly snow depth (element `SNWD`, start-of-period value, whole inches) from the
ultrasonic depth sensors of the USDA NRCS SNOTEL network (`SNTL` only; no SCAN,
SNOLITE or snow courses). One `uint8` sample per station and water year
(Oct 1 to Sep 30), WY2022 to WY2024.

## Source and license

- Endpoint: NRCS National Water and Climate Center Report Generator, `view_csv`
  (`https://wcc.sc.egov.usda.gov/reportGenerator/`). The AWDB REST API returned
  403 during scouting, so the recipe uses the CSV report endpoint instead.
- Station list: `sntl_stations_20261009.csv` holds the 934 SNTL stations
  (`Station Id,State Code,Elevation`) exported on 2026-10-09 from
  `customMultipleStationReport/daily/start_of_period/network="SNTL"|name/0,0/stationId,state.code,elevation`.
  It is pinned by sha256. `download.sh` also fetches the live list and logs any
  differences, for provenance.
- Per-station request:
  `customSingleStationReport/hourly/start_of_period/<id>:<ST>:SNTL|id=""|name/2021-10-01,2024-09-30/SNWD::value`.
- License: public domain. The data.gov entry "SNOwpack TELemetry Network (SNOTEL)",
  publisher NRCS, lists `license https://www.usa.gov/publicdomain/label/1.0/`
  and `Access Level public` (checked 2026-10-09). This is a U.S. federal
  government work.

## Pipeline

1. `download.sh` makes one curl GET per pinned station, waits 1 s between
   requests (`SNOTEL_SLEEP_SECONDS`) and uses curl retries. Each response is
   checked by `scripts/snotel_snwd.py check`. A valid response has the NRCS
   banner, `Reporting Frequency: Hourly`, the exact header
   `Date,Snow Depth (in)`, a site line that names the station, the confirmed
   date range, and only well-formed rows. Two kinds of reply count as `nodata`
   and are skipped and logged:
   - a comment-only reply such as `Stations do not exist  <id>:<ST>:SNTL`
   - a header-only reply

   Any other payload (HTML, a truncated file, malformed rows) is retried and
   then aborts the script. Size and sha256 of every response go to
   `download_plan.tsv`. Re-runs reuse files that already validate. Expect about
   934 requests, about 390 MB and roughly 45-60 minutes.
2. `build.sh` runs the parser self-test, then processes each station file:
   - skips `#` lines and drops hours with no row or an empty value
   - assigns each row to its water year
   - applies the fixed inclusion rules below
   - writes `samples/<id>/snotel_snwd_hourly_u8/<ST>_<id:04d>_wy<YYYY>.bin`,
     plus a matching auxiliary `snotel_snwd_hour_offset_u16` file holding the
     hours since Oct 1 00:00 local standard time

   Every station-year decision is listed in
   `filtered/<id>/station_year_stats.tsv`, and the totals are in
   `build_summary.json`.
3. `verify.sh` re-parses every source CSV with a separate code path (csv module
   plus ordinal-minute arithmetic). It re-derives the inclusion decisions and
   checks:
   - all bytes match exactly
   - index fields and manifest counts are consistent
   - no stray files are present
   - no sample is constant and no two samples are duplicates
   - the repository floors are met

   It also writes the mode share and zero share of every sample to
   `filtered/<id>/verify_mode_share.tsv` and prints their distribution.

## Inclusion rules (fixed before download)

Rules apply per station and water year:

- at least 1,000 valid hours
- every value integral and within 0..255. A negative or larger value excludes
  the whole station-year; nothing is clamped.
- at least 2 distinct values
- the most frequent value covers at most 80% of the valid hours. This removes
  years that are almost entirely snow-free and stuck-sensor years. Zero share
  is part of this rule, because zero is the mode in snow-poor years.

## Realized scope (build of 2026-10-09)

- Download: 934 pinned stations were requested. 905 returned hourly SNWD and
  29 were `nodata` (e.g. 201:AK, 1362:AK). Total 385,189,662 bytes in 2,776 s.
- Station-year decisions (905 stations x 3 water years, plus the 29 nodata
  stations):
  - 2,625 included
  - 49 too few hours
  - 25 mode-dominated
  - 14 out of range
  - 2 constant
- Primary output: 2,625 samples and 19,342,654 values or bytes. Lengths run
  from 1,034 to 8,784 values, median 7,770.
- By water year: WY2022 869, WY2023 880, WY2024 876. Thirteen states are
  covered: AK, AZ, CA, CO, ID, MT, NM, NV, OR, SD, UT, WA, WY.
- Auxiliary hour-offset output: 2,625 samples, 38,685,308 bytes.
- Across included samples, mode share has median 0.38, p90 0.55 and maximum
  0.798. The mode is zero in practically every sample (zero share median 0.38).
- Out-of-range exclusions: all 14 were values above 255 in. No station-year
  in the window contained a negative value. Some of these exclusions are real
  deep snowpack rather than spikes: 574:CA has 928 hours above 255 in during
  WY2022-23. The u8 width therefore drops a few of the deepest-snow
  station-years, while other exclusions come from a single spike hour (e.g.
  1310:NV, 525:WY).
- Sensor spikes: 1,204 of the 2,625 samples have at least one hour-to-hour
  jump of 24 in or more, 57,170 such jumps in total (about 0.3% of values).
  The global maximum kept is 251 in (1080:WA, WY2024). These spikes are left
  as published.

## Caveats

- Hourly SNOTEL data are provisional (QA flags R/P) and not fully
  quality-controlled. Ultrasonic spikes and dropouts inside 0..255 are kept as
  published.
- Values change slowly: in scouting, about 78% of hour-to-hour steps were 0.
  Snow-free months contribute genuine zeros. In 10 probed stations, zero share
  per station-year ranged from 0.13 to 0.68.
- Missing hours are common, mostly in summer, so sample lengths vary (about
  4,400 to 8,760 values in the probes).
- The card's no-data example `1085:CA` was a wrong triplet; station 1085 is
  Cayuse Pass, WA. The actual number of stations with hourly SNWD is reported
  by `download.sh` and `build_summary.json` rather than assumed.
- The source is live, so a later re-download can differ slightly as provisional
  data are revised. `verify.sh` checks against the hashes recorded at download
  time.
- Related local family: `noaa_ghcn_daily_snwd_by_station`, which is GHCN-Daily
  SNWD as int16 daily millimetres for 59 COOP (`USC`) and first-order (`USW`)
  stations, with no SNOTEL (`USS`) sites. This recipe differs in source,
  network, cadence (hourly), unit (inches) and width (u8).
