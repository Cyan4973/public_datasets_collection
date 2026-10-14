# DWWSSN Sprengnether long-period vertical (LHZ) seismograms, int16

Station-days of the long-period vertical channel of the **Digital World-Wide
Standardized Seismograph Network** (DWWSSN), FDSN network **DW** (1980-1994,
DOI 10.7914/SN/DW). The network was operated by the USGS Albuquerque
Seismological Laboratory (ASL). EarthScope (formerly IRIS DMC) serves it
through the FDSN web services.

- Channel `LHZ`, blank location, 1 sample/s.
- Only epochs recorded with the **Sprengnether Series 201 S-5007-V**
  seismometer at nominal scale 5.0E8 are used.
- Values are native DWWSSN digitizer counts. miniSEED data encoding 32 stores
  them as big-endian signed 16-bit integers, so the full int16 range is used.
- One sample is one UTC station-day: nominally 86,400 values (172,800 bytes)
  as little-endian int16. Whole records are kept verbatim, so a day holds
  85,536..86,410 values; a few early-1980s days run 1-5 samples past midnight
  because the last record straddles it.

## Scope

`plan.tsv` pins 651 station-days over 14 stations, 1980-1993. It was resolved
once, on 2026-10-14, by `discover.sh` / `scripts/discover.py`:

1. From the DW channel inventory, keep the LHZ epochs whose sensor is
   `Sprengnether Series 201 S-5007-V Seismometer`, scale 5.0E8, 1 sps.
2. Split each station's span of full days into 96 strata and pick one
   crc32-derived day per stratum (1,344 candidates).
3. Probe three 10-minute windows per candidate (03:00, 12:00 and 21:00 UTC)
   with dataselect POSTs. A candidate is present when record spans cover at
   least 570 of 600 s in every window. 948 candidates were present.
4. Take 48 present days per station, evenly spaced in time.

The FDSN availability service is retired (HTTP 404), which is why presence
was probed directly.

| Station | Sprengnether LHZ epoch | Plan days |
|---------|------------------------|-----------|
| AFI | 1981-05 .. 1987-04 | 48 |
| ALQ | 1981-03 .. 1982-08 | 48 |
| BDF | 1982-06 .. 1993-06 | 41 |
| COL | 1982-01 .. 1987-02 | 48 |
| GDH | 1982-08 .. 1993-10 | 48 |
| HON | 1983-03 .. 1990-10 | 48 |
| KBS | 1986-10 .. 1987-09 | 48 |
| KEV | 1981-10 .. 1987-03 | 48 |
| LEM | 1982-06 .. 1988-11 | 34 |
| LON | 1980-10 .. 1994-04 | 48 |
| SCP | 1981-01 .. 1992-09 (without the 1.0E9 epoch) | 48 |
| SLR | 1981-10 .. 1993-01 | 48 |
| TAU | 1981-08 .. 1993-10 | 48 |
| TOL | 1981-11 .. 1987-10 | 48 |

**Realized (build 2026-10-14): 512 samples, 88,473,738 bytes, all 14
stations, every year 1980-1993.** Per station: AFI 42, ALQ 42, BDF 23, COL 44,
GDH 41, HON 40, KBS 27, KEV 39, LEM 18, LON 38, SCP 38, SLR 41, TAU 43, TOL 36.
Skipped: 103 fill, 25 gap, 3 overlap, 4 short, 1 mostly clipped, 3 step noise.
Value counts: 86,400 for 448 days, 86,399 for 10 and 86,401..86,405 for 54.
Records are aligned to midnight, so the extra values come from the last
record running past it.

Pre-build estimate: on 28 spot-check days (two per station), 22 passed: 4 were skipped as fill (KBS twice, LEM, SCP) and 2 for gaps of about
400-450 s (BDF 1992, SLR 1991). From that rate, expect roughly 500 samples
(~85 MB).

## Exclusions (homogeneity)

- **Streckeisen STS-1 epochs.** From 1987 the STS-1 replaced the Sprengnether
  at AFI, COL, KEV and TOL. It has a different transfer function and much
  smaller counts: an AFI 1989 day spans only -64..53.
- **Geotech SL-210 stations** (BER, CMB, JAS, JAS1) and CMB's Guralp CMG3.
- **SCP 1990-12-07..1991-02-20.** The inventory lists this epoch at double
  gain (1.0E9).
- The horizontals LHE/LHN and every other channel.

The 28 spot-check days all sat in one regime: day extremes ±3,000 to ±19,700
counts, standard deviation 108-1,484, 778-7,666 distinct values. All records
were encoding 32, big-endian, 4096 bytes, 1 sps. Late epochs (BDF 1992,
GDH/LON/TAU 1993, SCP 1992) look the same as early ones.

## Decode and policy

`scripts/mseed.py` is a pure-stdlib miniSEED 2 reader. Header and blockette
handling are adapted from the accepted Apollo XA recipe, and the Steim decoder
is replaced by the DWWSSN 16-bit decoder.

`scripts/selftest_mseed.py` checks the reader against an independent synthetic
DWWSSN record encoder before every validate, build and verify run.
`verify.sh` also re-decodes every day with a second, minimal fixed-layout
decoder that does not use `mseed.py`.

A station-day is emitted only if all of these hold:

- Every record is `DW.<sta>..LHZ`, 1 sps, encoding 32, and overlaps the
  requested day. Anything else is fatal. Dataselect treats the request end as
  inclusive and returns whole overlapping records, so records that start
  before the day or exactly at the next midnight are dropped, not fatal.
- The records chain contiguously: sorted by start, exact duplicates dropped,
  each record starting within 1 sample of the previous nominal end. Probed
  days deviated by at most 0.4 samples.
- It holds 85,536..86,410 values.
- **Fill:** runs of 60 or more identical consecutive samples cover at most 1%
  of the day. On probed days, natural signal never repeated a value for more
  than 18 s. Fill runs were 8,000-33,000 samples of the value `128`.
- **Clipping:** at most 5% of the samples sit at |v| ≥ 32767.
- **Constant:** the most frequent value covers at most 50% of the day, and the
  day has at least 64 distinct values.
- **Step noise:** the median absolute first difference is at most 128
  counts. Accepted days have 0..53 (median 5). Three HON days in 1984-05..07
  show a broadband oscillation (median |step| 220-324, std ~7,000, ~25,000
  distinct values) unlike any other day, and are skipped as a malfunction
  regime. This threshold was set after inspecting the built output.

Days that fail are skipped whole and logged in
`filtered/<id>/ingest_stats.json`. Nothing is split, spliced or filled.

### Clipping and calibration

Large earthquakes drive the long-period channel to the int16 rails. The
candidate probe found TAU 1983-07-07 spanning -32767..32767 (sd 1,325). Such
days are kept unless more than 5% of their samples are clipped. Each index row
records `clip_count`, and `ingest_stats.json` totals the days with any
clipping.

Most days also show brief excursions of about ±15,000-17,500 counts against a
standard deviation of a few hundred. This is consistent with routine
calibration pulses, which are kept as genuine recorder output; it was not
verified day by day.

## License

DWWSSN data are a U.S. Government (USGS ASL) work:

- The FDSN DW page names the operator as "Albuquerque Seismological
  Laboratory/USGS (ASL)".
- The station service lists DW with `restrictedStatus="open"`.
- The USGS data-licensing page says federal works are "in the U.S. public
  domain, which means that anyone may use, copy, distribute, adapt, display
  and perform that work in the U.S. without permission". Data "wholly
  produced by USGS employees" are released under CC0.

`download.sh` re-fetches and checks all three. Several stations were hosted
by foreign institutions, but the instruments, digitizers and data
distribution were ASL's. No separate data terms are attached to the network
or its DOI.

## Access caveat (standalone reproducibility)

EarthScope has announced that **user authentication will be required for all
data downloads from 2026-12-15**. Anonymous dataselect works as of
2026-10-14, and this recipe uses only anonymous access. After that date,
re-running `download.sh` may need a free EarthScope login, which this recipe
does not supply. The accepted Apollo XA recipe has the same caveat.

## Scripts

- `download.sh` fetches the inventory, the network StationXML, the two
  license pages, and one miniSEED day per plan row (`nodata=404`). It rejects
  non-miniSEED or wrong-stream bodies on arrival, then validates the whole
  download. It fails if fewer than 300 days or 12 stations pass.
- `build.sh` and `verify.sh` use local files only.
- `discover.sh` documents how `plan.tsv` was resolved. It is not part of the
  build.
