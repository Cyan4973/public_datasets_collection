# Fingrid Nordic grid frequency, 10 Hz, daily records (float32)

This recipe collects the electrical frequency of the Nordic synchronous power
system, as measured by the Finnish TSO Fingrid at 400 kV substations, sampled
every 0.1 s. Fingrid publishes it as dataset 339, "Frequency - historical
data": monthly 7z archives that each hold one `Time,Value` CSV per day. The
recipe keeps only Fingrid's primary measurement chain, which publishes at
10 µHz resolution; see "Measurement chain and resolution rule" below.

- Source page: https://data.fingrid.fi/en/datasets/339
- License: Creative Commons Attribution 4.0. The page metadata gives
  `license.name = "Creative Commons Attribution"` and
  `termsLink = https://creativecommons.org/licenses/by/4.0/`. `download.sh`
  re-checks both on every run. Attribution: Fingrid Oyj, Fingrid Open Data.
- Access: anonymous HTTPS under `https://data.fingrid.fi/files/339/...`. The
  Fingrid open-data API needs a key, but these file downloads do not.

## Scope

There are three pinned monthly archives, 93 daily CSVs in total:

| month | archive bytes | codec | decoded CSV bytes | notes |
|---|---:|---|---:|---|
| 2025-01 | 66,380,610 | LZMA (LZMA1), 8 MiB dict | 907,390,195 | `2025-01/` directory entry |
| 2025-07 | 67,980,333 | LZMA (LZMA1), 8 MiB dict | 905,667,530 | members not in date order |
| 2026-01 | 65,159,455 | LZMA (LZMA1), 8 MiB dict | 906,867,671 | `2026-01/` directory entry |

The download is 199,520,398 bytes, plus the roughly 126 KB dataset page. The
months were chosen as follows:

- Each sits away from a DST transition. Timestamps are Finnish local time,
  UTC+2 or UTC+3, so every daily file is a plain 00:00:00.0 to 23:59:59.9 day.
- Together they cover two winters and one summer across 2025 and 2026, so the
  material spans different load, hydro and inertia regimes.
- All are from 2025 onward, where the published data come from a single
  measurement chain.

The full day lattice is 864,000 values. Realized output (build of
2026-10-06, repair 1):

- 93 of 93 days kept, with no exclusions under either day rule. Kept
  `coarse_token_share` runs from 0.00987 to 0.01038, against the 0.02 limit.
- 80,261,336 float32 values, 321,045,344 bytes.
- Per-day value counts range from 853,202 to 864,000; the median is 863,917.
- Values span 49.76575 to 50.42852 Hz. The extremes include isolated
  single-sample spikes; see below.
- 90,676 ticks are missing over all days (0.11%).
  - 12 days are missing more than 1,000 ticks: 8 in 2025-07, 3 in 2026-01
    and 1 in 2025-01.
  - The longest gap is 10,761 ticks, about 18 minutes, on 2025-07-08, whose
    coverage is 98.75%.
- 12 duplicate-timestamp rows.
- Aggregate sample SHA-256, over samples in index (date) order:
  `3bffe84e6b861e124c30399c134be0f56ec5d12bfa87c358ad4ec8825064fa2f`.

Date order matters because 2025-07 does not store its members in date order.
Archive SHA-256s are pinned in `sources.tsv` and the manifest.

Fingrid's separate 3-minute real-time frequency product is not mixed in. Only
the 10 Hz historical measurements are used.

## Conversion

1. `download.sh` does the following:
   - fetches the dataset page and validates the license and the file
     listing (link and byte size for each pinned month);
   - fetches each archive whole and resumably
     (`curl -C - --speed-limit 1024 --speed-time 120`, retried in a loop);
   - checks the byte size, the Azure `Content-MD5`, and the SHA-256 once it
     is pinned;
   - checks the 7z member list against `members.tsv`: names, sizes and CRC32s
     for all 93 members;
   - fully decodes the archive and verifies every member's CRC32 before
     renaming it into place.
2. `build.sh` (`scripts/fingrid_frequency.py build`) re-checks archive
   identity. It then stream-decodes each solid folder with
   `scripts/sevenzip.py` and splits it by the header's substream sizes,
   re-checking each CRC32. This reader is pure stdlib: it parses the start
   header, decodes the encoded header with raw LZMA1, and decodes the main
   folder with raw LZMA1 (raw LZMA2 is also supported). Each daily CSV is
   then parsed:
   - the header must be exactly `Time,Value`;
   - every timestamp must fall on the file's date and on the 100 ms lattice;
   - every value must be a plain decimal with at most 5 fractional digits,
     between 45 and 55 Hz.

   Each value is converted to the nearest float32. Each distinct token is
   checked to round-trip exactly, which it always does near 50 Hz: the
   float32 ulp is 3.8e-6 and the half-step of the printed decimals is 5e-6.
   The two day rules below are then applied. Each kept day's values are
   written in CSV row order to
   `samples/<id>/nordic_grid_frequency_10hz_f32/<YYYY-MM-DD>.bin`.
3. `verify.sh` (`scripts/fingrid_frequency.py verify`) re-decodes the
   archives and re-parses each day through a separate code path:
   - the `csv` module, `datetime.fromisoformat`, `Decimal` and `array('f')`,
     instead of the build's fixed-width slicing and `struct` caches;
   - it byte-compares every sample;
   - it re-derives every per-day statistic stored in the index, including
     `coarse_token_share`;
   - it rejects any indexed day that fails a day rule, and requires every day
     that passes both rules to be indexed;
   - it rejects degenerate days (fewer than 100 distinct values, or a range
     under 0.01 Hz);
   - it checks the manifest scope.

## Day rules (pinned, identical in build and verify)

1. **Coverage.** At least 777,600 of the day's 864,000 0.1 s ticks (90%)
   must carry a value.
2. **Resolution.** `coarse_token_share` must be at most 0.02. This is the
   share of the day's Value tokens printed with 3 or fewer decimals:
   `sum(decimals_histogram[0:4]) / value_count`.

Each index row and each `filtered/<id>/day_stats.jsonl` line records
`coarse_token_share` and any exclusion reasons.
`filtered/<id>/build_summary.json` lists the excluded days. Individual rows
are never dropped by either rule; a day is kept or excluded whole.

## Measurement chain and resolution rule

The first revision of this recipe used 2024-01, 2024-07 and 2025-01. The 2024
archives contain hour-aligned stretches from what appears to be a smoothed
backup measurement chain, published at 1 mHz (3 decimals) instead of the
primary chain's 10 µHz (5 decimals). The evidence:

- **Prevalence.** 53 of the 93 days in that build contained at least one
  such clock hour: 28 of 31 days in 2024-01 and 25 of 31 days in 2024-07.
  Together they made up 97 of 2,232 hours, or 3,486,404 rows (4.3%).
  2025-01 had none.
- **Separation.** `coarse_token_share` was 0.0099 to 0.0103 on all 40 clean
  days. That residual is 5-decimal values whose trailing zeros are stripped
  (for example 50.01000 printed as 50.01). Every day with a 1 mHz hour was at
  0.051 or above, up to 0.299.
- **Different instrument or filter, not just rounding.** The coarse hours
  switch in exactly at hour boundaries with no level jump, but behave
  differently. On 2024-07-11, which had 7 coarse hours and 17 fine hours:
  - in fine hours the sample-to-sample differences jitter, with a median
    lag-1 autocorrelation of −0.19 and a median mean step of 0.86 mHz;
  - in coarse hours they are smoothed, with a lag-1 autocorrelation of
    +0.25 and a mean step of 0.50 mHz.

  The acceptance judge measured the same opposite signs independently.

Mixing the two chains would put two generation processes and two lattices
inside one family. The 2024 months were therefore replaced with 2025-07 and
2026-01, and the resolution rule pins the single-chain property.

Before the swap, the first full day of each new month was decoded from 4 MB
prefix range requests, and all sat at the clean level: 2025-07-29 at 0.0100
and 2026-01-01 at 0.0103. The judge's own probes of the first ~2 days of
2025-07, 2025-12 and 2026-01 (143 hours) also found no coarse hours. Zero
exclusions are expected. If a month lost more than 3 days to the rules, it
would be replaced rather than shipped thinned.

## Other source properties

- **Gaps.** Fingrid notes that "the data may contain some gaps due to
  telecommunication errors". Missing rows are never filled or interpolated.
  A sample holds exactly the rows present. The index records, per day:
  covered and missing 0.1 s ticks, gap count, longest gap, and
  duplicate-timestamp rows. `day_stats.jsonl` also lists the gap runs, each
  as a start tick and a length. Ten days have a single gap of 4,000 to
  10,761 ticks (about 7 to 18 minutes): six in 2025-07, three in 2026-01 and
  one in 2025-01. The lowest-coverage day is 2025-07-08 at 98.75%.
- **Hour-boundary duplicates.** The daily files are joined from hourly
  pieces, so some hours repeat the `HH:00:00.000` row, either as an exact
  copy or with the value from the next piece. These rows are emitted as
  present. All 12 in the realized output fall on the first day of a month,
  4 each on 2025-01-01, 2025-07-01 and 2026-01-01.
- **Isolated spikes.** The published data contain a few single 0.1 s
  samples that sit far from both neighbours. The largest is 50.42852 Hz on
  2025-07-17, between 50.0136 and 50.0608; the next is 50.3877 Hz on
  2025-07-31. Counting samples more than 50 mHz from both neighbours, there
  are 16 among the 80.26 million values, on 10 days, nearly all in 2025-07.
  These are measurement artifacts, not physical frequency excursions, but
  they are published values, and bsdtar extraction of 2025-07-17 reproduces
  the spike. They are kept as published; no outlier filtering is applied.
- **Narrow dynamic range.** Values stay near 50 Hz (49.77 to 50.43 Hz),
  so the float32 exponent and upper mantissa bits are nearly constant. The
  information sits in the low mantissa bits and in the 10 Hz dynamics.
- **Independent decoder cross-check.** bsdtar (libarchive 3.5.3) produced
  CSVs byte-identical to the pure-stdlib reader (same size and CRC32 as
  pinned), and re-parsing them reproduced the emitted samples exactly. The
  days checked were:
  - 2025-01-31, the final member of its archive (previous revision);
  - 2025-07-29, the first, out-of-order member of 2025-07;
  - 2025-07-17, the day with the largest spike;
  - 2026-01-31, the final member of its archive.

## Files

- `sources.tsv`: pinned archives (URL, size, Content-MD5, Last-Modified,
  and SHA-256, or `-` until it is pinned).
- `members.tsv`: pinned 7z members (name, size, CRC32) for all 93 days, in
  archive order.
- `discover.sh`: how both tables were resolved, using only the dataset page,
  HEAD requests and three small byte ranges per archive (start header, next
  header, packed header).
- `scripts/sevenzip.py`: minimal stdlib 7z reader. Self-tested on
  libarchive-written LZMA1 and LZMA2 archives, including directory entries,
  injected corruption, truncation and CRC mismatch.
- `scripts/fingrid_frequency.py`: download validation, build and verify.

```bash
bash staging/fingrid_nordic_grid_frequency_10hz_f32/download.sh
bash staging/fingrid_nordic_grid_frequency_10hz_f32/build.sh
bash staging/fingrid_nordic_grid_frequency_10hz_f32/verify.sh
```
