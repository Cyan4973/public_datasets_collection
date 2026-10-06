# RWTH ISEA home-storage battery pack voltage, 1 Hz, float32 (48 V class)

Field measurements of privately operated residential PV home storage systems
(HSS), recorded by ISEA/CARL at RWTH Aachen University from 2015 to 2022
(Figgener et al., Nature Energy 2024). Zenodo record
[12091223](https://zenodo.org/records/12091223) is CC BY 4.0 per its record
metadata. It holds 21 systems, 106 system-years, 1,270 monthly CSVs and
14 billion data points at a 1 s sample rate.

This recipe emits one quantity: the battery pack terminal voltage `V_in_V`
(volts). Each sample is one complete system-month as a little-endian float32
array, one value per second in file order (2,419,200 to 2,678,400 values).

## Scope and homogeneity

- Systems 1-6 are 146.7 V packs with 40 cells in series
  (`Metadata_Systems.xlsx`), a different scale, so they are excluded.
- Systems 7-21 are 46-51.8 V nominal packs: manufacturer B NMC 13s,
  C NMC 14s, D NMC 14s, and E LFP 14s/16s. Their observed voltages fall
  between roughly 43 and 58 V.
- Prefix probes of every system showed that 13 of the 15 systems print
  logged voltages with six significant digits, mostly in 0.1-0.6 mV steps.
  System 13 prints 1 mV steps (5 significant digits) and system 17 prints
  10 mV steps, in every month probed. Those coarser lattices are a different
  quantization regime, so both systems are excluded. Build and verify enforce
  the lattice: at least half of each month's logged tokens must have six
  significant digits (the kept systems measure about 0.85-0.9).
- System 18 is excluded as well. Its three original months were partial
  (2017-04, 2018-02) or contained a 46-minute disconnection at about
  0.09 V (2016-10), and its remaining months are visibly partial by size.
- Kept systems: 7, 8, 9, 10 (B), 11, 12 (C), and 14, 15, 16, 19, 20, 21 (E).
  Each contributes 3 calendar months spread over its record and the
  seasons, for 36 samples:

| system | months |
|---|---|
| 07 | 2016-08, 2019-11, 2022-05 |
| 08 | 2016-07, 2019-01, 2022-06 |
| 09 | 2016-06, 2018-12, 2022-08 |
| 10 | 2018-09, 2020-01, 2022-05 |
| 11 | 2019-12, 2021-05, 2022-08 |
| 12 | 2019-07, 2021-02, 2022-09 |
| 14 | 2015-09, 2017-11, 2020-04 |
| 15 | 2016-08, 2020-05, 2022-07 |
| 16 | 2019-06, 2020-12, 2022-08 |
| 19 | 2016-04, 2017-12, 2020-07 |
| 20 | 2016-09, 2018-07, 2020-01 |
| 21 | 2016-09, 2018-01, 2020-06 |

Realized output: 36 samples, 95,040,000 values, 380,160,000 bytes. Samples
hold 2,419,200 to 2,678,400 values (median 2,678,400) and 9,494 to 117,403
distinct values each. They span the years 2015-2022 (2015: 1, 2016: 7,
2017: 2, 2018: 4, 2019: 5, 2020: 7, 2021: 2, 2022: 8). Stored values range
from 42.51 to 63.04 V; the maximum is a single reading, noted below.

### Selection history

Candidate months were those whose uncompressed bytes per second match the
system's full months for that calendar month (`discover.sh` prints the
list). Size cannot show short gaps, so the selection was settled over two
download/build rounds. Each candidate that failed the policy below was
replaced by the next candidate in a fixed order. Twelve candidates failed:

| candidate | failure |
|---|---|
| 10/2017-06 | 102,711 missing seconds (2 gaps) |
| 10/2022-07 | 1,588 missing seconds (1 gap) |
| 10/2017-07 | 76,447 missing seconds (1 gap) |
| 10/2018-05 | 85,132 missing seconds (2 gaps) |
| 10/2022-06 | 1,573 missing seconds (1 gap) |
| 15/2022-01 | 135,465 missing seconds (3 gaps) |
| 18/2017-04 | 218,461 missing seconds (4 gaps; data start 2 Apr 00:59:35) |
| 18/2018-02 | 139,890 missing seconds (3 gaps) |
| 14/2017-12 | final ~30 h at ~0.14 V (pack disconnected) |
| 18/2016-10 | 2,791 s at ~0.09 V (pack disconnected) |
| 21/2016-08, 21/2017-08 | isolated `0` V readings (3 and 1) |

Four round-2 candidates passed but were not used because their slots were
already filled: 10/2022-08, 14/2018-12, 15/2022-09 and 15/2022-11. Keeping
three months per system holds the systems in balance. All 16 unselected
spans are removed by the prune step in `download.sh`.

Round 1 settled one question: 18/2016-10 has every second exactly once
across the 30 Oct 2016 clock change, so the timestamps do not observe DST.

## Missing values, interpolation, conversion

- Completeness: a month is kept only if it has exactly `days*86400` rows
  whose `Time` field is every second of the month in order. Gaps,
  duplicates or DST shifts fail the build, and the selection then has to be
  revised. Partial months are never emitted.
- `V_in_V` must be a finite decimal in [25, 65] V. Blank or NaN is fatal.
  The only out-of-range readings seen were 0 V or about 0.1 V while a pack
  was disconnected. Those are missing-value readings, not pack voltages, so
  the affected months were dropped. In-range values are never clipped or
  edited. 21/2016-09 contains one 1 s reading of 63.04 V during a 75 A
  charge, above that 14s LFP pack's normal range of about 43-50 V. It is
  kept as published.
- `Interpolated=1` marks the publisher's linear fills of short gaps. Probes
  found about 6% in a few 2017-2018 system-07 months, which are not
  selected. A month is rejected if more than 1% of its rows are
  interpolated. In the realized output the share is at most 0.040% per
  month (median 0.0006%): 4,712 interpolated rows in total, and 11 of 36
  months have none. 3,664 of those rows carry more than six significant
  digits and are therefore not exact in float32. The interpolated rows stay in place to keep the 1 Hz
  lattice. Their per-month count and share are in `samples.jsonl` and their
  `[start, length]` runs in
  `filtered/<id>/interpolated_runs/system_<SS>_<YYYY_MM>.json`.
- Conversion: decimal text is rounded once to IEEE-754 binary32. Logged
  values have at most six significant digits, so the conversion is exact:
  `%.6g` of the stored float32 equals the source decimal, and build and
  verify both check this. Interpolated values, printed with up to 15
  significant digits, are rounded to the nearest float32.

## Acquisition

The per-system zips are 0.33-2.15 GB, so `download.sh` never fetches whole
archives. `discover.sh` (metadata only) reads the record JSON and the last
128 KiB of each zip, parses the central directory (no ZIP64 needed; members
are deflate with flags 0), and reproduces `selection.tsv`. That file pins
each member's archive, offset, span, sizes and CRC32.

`download.sh` then:

1. fetches the record JSON and rejects HTML or error bodies, license changes
   (must be `cc-by-4.0`), or archive size/MD5 changes;
2. fetches the 31 KB `Metadata_and_Code.zip` and checks its MD5;
3. range-fetches each member span sequentially, with a pause between
   members. curl uses `--fail`, retries with backoff, and a stall-based
   `--speed-limit`. Each chunk is appended only after the final response is
   a 206 with the exact `Content-Range`, so partial spans resume. The local
   header must start with `PK\x03\x04` and match the pinned name, method,
   CRC32 and sizes. The whole deflate stream is inflated, and its CRC32,
   uncompressed size, exact end-of-stream and CSV header are checked.
   Span SHA-256s go to `member_validation.tsv`.

Transfer: 806,046,462 bytes of member spans plus about 0.1 MB of metadata.
Inflated CSVs (5.56 GB) are never written to disk. The two selection rounds
also fetched 16 candidate spans that are not in the final selection (12
failed, 4 unused). A step at the end of `download.sh` deletes spans that are
not in the selection.

```bash
bash staging/rwth_isea_home_storage_battery_voltage_f32/download.sh
bash staging/rwth_isea_home_storage_battery_voltage_f32/build.sh
bash staging/rwth_isea_home_storage_battery_voltage_f32/verify.sh
```

`build.sh` and `verify.sh` use only local files. `verify.sh` is a separate
implementation (csv.reader over a streaming inflate, arithmetic timestamp
parsing, Decimal round-trip check). It byte-compares every sample, recomputes
index min/max from the stored float32 values, and rejects samples with fewer
than 100 distinct values, a range under 0.5 V, a duplicate, an extra or
missing file, or a manifest count/size mismatch.

## Notes

- Novelty: field-logged DC pack voltage of residential batteries. The only
  local battery family, `zenodo_battery_eis_complex_f32`, holds laboratory
  impedance spectra, a different quantity and record shape.
- Chemistries and series counts differ (NMC 13s/14s versus LFP 14s/16s,
  with LFP's flatter voltage plateau), so per-system operating bands range
  from about 43-50 V to 45-57.5 V. Unit, scale, logger lattice (six
  significant digits, 0.885-0.904 of logged tokens), 1 Hz cadence and
  campaign are shared.
- Only `V_in_V` is emitted. Power, current and temperature are separate
  quantities and stay out of this family.
