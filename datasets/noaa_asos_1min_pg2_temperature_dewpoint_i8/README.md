# NOAA ASOS One-Minute Page-2 (DSI 6406) Air Temperature and Dew Point Int8

This recipe collects 1-minute air temperature and dew point in whole degrees
Fahrenheit from the U.S. Automated Surface Observing System (ASOS). The source
is NCEI data set DSI 6406 ("1-minute page 2"). Each station-month file yields
two primary int8 series:

| series | source field | unit |
| --- | --- | --- |
| `air_temperature_degf_i8` | average 1-minute dry-bulb temperature | deg F |
| `dew_point_temperature_degf_i8` | average 1-minute dew-point temperature | deg F |

Other page-2 fields are not emitted: precipitation type and amount, lightning,
freezing-rain sensor frequency, and the three station pressures. The pressures
are three-decimal inHg and so are not native 8-bit.

## Scope

- 44 ASOS stations chosen for climate spread:
  - desert Southwest: KPHX KIPL KMAF KABQ KLAS
  - Great Basin and Rockies: KELY KGJT KSLC KCPR KHLN KBIL KRNO
  - Pacific coast: KSEA KPDX KSFO KSAN KMFR
  - northern and southern Plains: KABR KMOT KINL KMSP KDDC KOKC
  - Midwest: KORD KDTW KIND KSTL
  - South and Gulf: KIAH KMSY KMEM KJAX KMIA KEYW KCHS KRDU
  - Northeast: KBOS KBTV KPWM
  - Alaska: PAFA PANC PAJN PATO
  - Hawaii and Puerto Rico: PHNL TJSJ
- Year 2022, 509 station-month files totalling 2,400,428,490 bytes, pinned in
  `sources.tsv`. The 80% rule below skips 19 station-months: KLAS-06, PAFA-02,
  -06, -10 and -11, PAJN-05, -11 and -12, PANC-04, -05, -10, -11 and -12, and
  TJSJ-04, -05 and -09 to -12.
- The build-time coverage rule below then excludes 9 of the 509 downloaded
  station-months, leaving 500 (44 stations) per series.
- Natural record: one station-month `.dat` file. One sample is one
  station-month for one series, so there are 1,000 samples of up to 44,640
  values each.

### Why 2022 and not 2024 (the year on the candidate card)

NCEI's 2024 page-2 files have outages across the whole network:
- In September 2024, no station has more than 80% of its minutes.
- In May 2024 the best station has 88%; in October, 90%.

The 2023 files are worse. June 2023 tops out at 34% and December 2023 at 14%.

In 2022, every month has stations at 95-100% and the monthly medians are
91-99%. Following the screener's instruction to avoid large outages, the
recipe pins 2022.

### Selection rule

A station-month is kept when its listed size is at least 80% of a complete
month (days × 1440 × 113 bytes). Shorter files contain long outages, so they
are skipped rather than kept as small samples.

The same rule applies to every station. Alaska and Puerto Rico lose some months
because no Alaska station has 12 complete 2022 months. PABR (Utqiagvik) was
dropped because none of its months passes.

The size rule cannot detect a sensor outage inside a full-size file. KDTW
March-May 2022, for example, reports every minute, but the hygrothermometer
slots are `[ M ]` for most or all of them. So the build applies a second,
content-based rule to every downloaded file: a station-month is kept only if
both series have valid values for at least 80% of the calendar month's
minutes. Otherwise it is excluded for both series and listed with its
coverage in `filtered/<id>/ingest_stats.json`. In 2022 this excludes 9
station-months:

| station-month | valid temperature / dew point coverage |
| --- | --- |
| KDTW 2022-03 | 0.379 / 0.379 |
| KDTW 2022-04 | 0.000 / 0.000 |
| KDTW 2022-05 | 0.228 / 0.227 |
| KEYW 2022-04 | 0.756 / 0.998 (bracket-flagged temperature run) |
| KEYW 2022-07 | 0.961 / 0.611 (bracket-flagged dew-point run) |
| KINL 2022-12 | 0.354 / 0.354 |
| PATO 2022-11 | 0.629 / 0.629 |
| PATO 2022-12 | 0.809 / 0.765 |
| PHNL 2022-11 | 0.780 / 0.780 |

These files remain in the download set because `sources.tsv` is the
listing-only selection; the exclusion is recomputed independently by
`verify.sh`.

`discover.sh` regenerates `sources.tsv` from the twelve directory listings,
fetching listings only. Rerun it only if NCEI republishes files and the pinned
sizes stop matching.

## Format and decoding

DSI 6406 files are fixed-width ASCII, 112 characters plus LF per line. The
documentation (`doc/asos-1min-pg2_documentation.pdf`, 2022-11-08) gives the
field order but not the column positions. The columns below were measured on
2022 and 2024 files. Example:

```
03017KDEN DEN2022010100000700   S-  0000    0.00              39997   24.355  24.338  24.347    8    5
```

Columns, as 0-based slices:

| slice | content |
| --- | --- |
| `[0:5]` | WBAN |
| `[5:9]` | ICAO |
| `[13:29]` | LST date and time, then UTC time |
| `[29:92]` | precipitation id and intensity, lightning, 1-minute precipitation amount, freezing-rain sensor frequency, three station pressures |
| `[92]` | blank, or the `]` closing a bracketed third pressure |
| `[93:98]` | temperature slot |
| `[98:103]` | dew-point slot |
| `[103:]` | blank |

Each slot holds one of three things:
- a value, right-justified in the middle three characters (`"  26 "`,
  `" -12 "`, `" 104 "`);
- the same value in square brackets (`"[ 41]"`);
- a missing marker: `"[ M ]"`, `"  M  "` or blanks.

The other fields vary from row to row. Precipitation can be `M` or `[ M ]`,
the freezing-rain frequency can be blank, and lightning and pressure can be
bracketed. The slots are read from fixed columns, so none of this moves them;
the probe confirmed it.

A row counts as structural when all of these hold:
- it is printable ASCII and at least 103 characters long;
- it starts with a 5-digit WBAN and the expected ICAO;
- it has 16 timestamp digits whose LST year and month match the file;
- column 92 is a blank or `]`;
- both slots are well formed;
- columns 103 and later are blank.

These checks reject shifted or truncated records. Rows that fail them are
dropped for both series and counted, and the build fails if they exceed 5% of
any file.

Within structural rows, these values are dropped for that series only and
counted:
- missing values;
- bracketed values (see the caveats);
- values outside -128..127.

About 0.25% of minutes appear twice: a second consecutive record with the same
LST timestamp, often carrying slightly different pressures and temperature
(53,428 such rows in scope; about a quarter of them differ in the
temperature/dew-point slots). Only the first structural row of each LST minute
is used; later ones are dropped for both series and counted. Each sample
therefore has at most one value per minute.

Nothing is imputed. Values are written as int8 in file (time) order, so a
sample is the sequence of valid minutes, not a gap-filled lattice.

`verify.sh` re-parses every file with an independent full-line regex. It
checks:
- sample bytes and sha256;
- the index fields, including min/max of the stored int8 values;
- the missing, flagged, out-of-range, duplicate-minute and bad-row counts
  against the build;
- the set of station-months excluded by the coverage rule;
- the manifest totals.

It also rejects any sample with fewer than 1,000 values, fewer than 3 distinct
values, or a single value covering 80% or more of it.

## Realized output (2022 build)

| series | samples | bytes | values per sample (min / median) | range |
| --- | --- | --- | --- | --- |
| `air_temperature_degf_i8` | 500 | 20,775,709 | 33,562 / 42,157 | -78..117 °F |
| `dew_point_temperature_degf_i8` | 500 | 20,763,794 | 33,384 / 42,020 | -68..127 °F |

Ingest counts over all 509 downloaded files (21,242,730 rows): 1,059 malformed
rows (649 layout, 410 slot), 53,428 duplicate-minute rows, missing 168,709
temperature / 172,900 dew point, bracket-flagged 28,389 / 43,234, and 72
dew-point values above 127 dropped as out of range. The largest single-value
share in any sample is 0.18 for temperature and 0.32 for dew point; the
medians are 0.05 and 0.07.

## Probe evidence (2026-10-09, range requests only)

I took 300-400 KB slices of 18 station-months:
- 2022: KDEN-01, KPHX-07, PAFA-01, KMIA-08, KSEA-11, KORD-02, KBOS-12, KLAS-06,
  PABR-02, TJSJ-05;
- 2024: KDEN-01, KPHX-07, PAFA-01, KMIA-08, KSEA-11, KORD-07, PHNL-05, KBOS-02.

Results:
- All complete lines were 112 characters.
- The temperature and dew-point slots matched the shapes above in every row.
- Observed ranges ran from -45/-53 °F (PAFA January 2022, temperature/dew
  point) to 114 °F (KPHX July 2024).
- About 0.1% of rows were missing a slot; under 0.03% were bracketed.

The build and verify parsers agreed byte-for-byte on all probes and on a
synthetic edge-case file containing:
- missing, blank and bracketed values, plus a bracketed pressure;
- the out-of-range values 128 and 999;
- a malformed digit field, a `+` sign, an unbalanced bracket and garbage in the
  tail;
- a row from another month and one from another station;
- a short line, a non-ASCII byte and CRLF.

The stored int8 bytes round-tripped to the synthetic input values.

## License

These are federal works of NWS, FAA, DoD and NCEI (17 U.S.C. 105). The NCEI ISO
record `gov.noaa.ncdc:C00387` uses MD_RestrictionCode `otherRestrictions`, and
the only texts under it are:
- "Cite as: NOAA National Weather Service, U.S. Federal Aviation
  Administration, U.S. Department of Defense, NOAA National Centers for
  Environmental Information (2005): 1-Minute Page 2 Surface Weather
  Observations from the Automated Surface Observing Systems (ASOS) Network ...
  NCEI DSI 6406_02";
- the distribution-liability disclaimer;
- the use-liability disclaimer.

None of these restricts use. `download.sh` saves the record and checks its
text.

## Novelty and caveats

- Local temperature material:
  - GHCN-Daily TMAX/TMIN/TAVG: daily, tenths of °C, 16-bit;
  - ISD-lite: hourly, tenths of °C, int16;
  - CO-OPS air temperature: 6-minute, float64, three stations.
- Downstream, the UCI appliances-energy set has a `Tdewpoint` family at 32/64
  bits. Its registry lists an 8-bit variant of that dataset, but that is
  10-minute data from one site, not station observations.
- No local or downstream family has minute-cadence station temperature or dew
  point at 8 bits. This is a new source and cadence, not a new modality.
- `noaa_asos_1min_pg1_wind_speed_u8` is a sibling staging recipe from the same
  NCEI ASOS one-minute program. It uses a different DSI product, file set,
  sensor and quantity, and its own download directory; no files are shared.
- The two series are strongly related, since dew point never exceeds
  temperature in valid data. The scout's feature probe put them 0.042 apart.
  They are separate primary series of one recipe, not separate families.
- Extraction ratio: about 2 bytes kept per 113-byte line, roughly 43 MB of
  primary data from 2.40 GB downloaded. NCEI offers no field-projected
  download, and IEM's 1-minute service is a third-party re-serve.
- NCEI states that the data are not edited. In-range sensor glitches therefore
  remain. In the realized output, 704 dew-point values (0.003%) exceed 90 °F,
  which is physically implausible. Most are at PATO (615 values across 9
  months), with the rest at TJSJ-03 (48), KMSY-01/02 (14), PHNL-05 (13), KMOT-04
  (11) and KSTL-02 (3). One temperature value of -78 °F occurs at KMSP 2022-08. They
  are kept as recorded rather than edited by a recipe-invented QC threshold.
- The brackets are not defined in DSI 6405 or 6406 documentation. Dropping
  bracketed temperature and dew-point values is a conservative choice; it
  affects 0.13% (temperature) and 0.20% (dew point) of rows in scope.
