# Fingrid Nordic grid frequency 10 Hz float32 development

## Outcome

Accepted `fingrid_nordic_grid_frequency_10hz_f32`: the electrical frequency of the Nordic synchronous power system, measured by Fingrid at 400 kV substations in Finland at 10 samples per second. Each sample is one daily CSV.

The first revision used 2024-01, 2024-07 and 2025-01. The first judge round sent it back for repair: 53 of the 93 days in the 2024 archives contain whole clock hours from a smoothed backup measurement chain. That chain prints 1 mHz (3 decimals) instead of the primary chain's 10 µHz (5 decimals), and its sample-to-sample steps have the opposite autocorrelation sign.

Repair 1 made two changes:
- It replaced the 2024 months with 2025-07 and 2026-01.
- It added a pinned per-day resolution rule, applied identically in build and verify: `coarse_token_share = sum(decimals_histogram[0:4]) / value_count` must be at most 0.02. Clean days measure about 0.010; any day containing a backup-chain hour measures at least 0.051.

The rule excludes nothing in the pinned months.

## Source and rights

- Source: Fingrid Open Data, dataset 339 "Frequency - historical data", https://data.fingrid.fi/en/datasets/339
- License: Creative Commons Attribution 4.0. The dataset page metadata gives `license.name = "Creative Commons Attribution"` and `termsLink = https://creativecommons.org/licenses/by/4.0/`. `download.sh` re-validates both on every run.
- Access: anonymous HTTPS `/files/339/` downloads. The open-data API needs a key, but these file downloads do not.
- Pinned archives (size, Azure Content-MD5, Last-Modified, SHA-256):

| month | bytes | SHA-256 |
|---|---:|---|
| 2025-01 | 66,380,610 | `762ed181c6aa8793c31edbe8555bb446d2875061d80767604cb49fb984eca549` |
| 2025-07 | 67,980,333 | `393756cd7ec25d99d81f9affcc8e96e12788443e1fcd3f9b35e94b8327bfa9bc` |
| 2026-01 | 65,159,455 | `f63627e68bad463df49adff4fc697251266e956acd88b4e6faba4440844499a9` |

- Total download: 199,520,398 bytes, plus the roughly 126 KB dataset page.
- `members.tsv` pins the name, size and CRC32 of all 93 7z members.

## Shape and conversion

**Natural record.** One `Taajuusdata<YYYY-MM-DD>.csv` (`Time,Value`, Finnish local time, 0.1 s lattice) inside a monthly solid 7z archive. All three archives use LZMA1 with an 8 MiB dictionary and an encoded header.

**Decoding.** A pure-stdlib reader parses the 7z headers and stream-decodes the folder with raw LZMA1. It splits the stream by substream sizes and checks every member's CRC32.

**Conversion.** Each Value token (at most 5 decimals, 45–55 Hz) is converted to the nearest float32. Both build and verify check that every token round-trips exactly: near 50 Hz the float32 ulp/2 is 1.9e-6, below the 5e-6 half-step of the printed decimals.

**Output.** Values are written in CSV row order as raw little-endian float32, one file per day. Telemetry gaps are never filled. Rows repeated at hour joins (`HH:00:00.000`) are emitted as published.

**Day rules (identical in build and verify):**
1. Coverage: at least 777,600 of the day's 864,000 ticks carry a value.
2. Resolution: coarse_token_share is at most 0.02.

verify rejects any indexed day that fails a rule and requires every passing day to be indexed.

**Month choice.** The three months contain no DST transition and cover two winters and one summer across 2025–2026.

## Accepted output

- Days parsed: 93; samples kept: 93; excluded: 0
- Kept coarse_token_share: 0.009873–0.010379
- Primary values: 80,261,336
- Primary bytes: 321,045,344
- Minimum sample: 853,202 values (2025-07-08)
- Median sample: 863,917 values
- Maximum sample: 864,000 values
- Value range: 49.76575–50.42852 Hz. The extremes are isolated single-sample spikes: 16 values more than 50 mHz from both neighbours, on 10 days, kept as published.
- Missing ticks: 90,676 (0.11%)
  - 12 days miss more than 1,000 ticks.
  - The longest gap is 10,761 ticks (about 18 min, 2025-07-08), and the lowest day coverage is 98.75%.
- Duplicate-timestamp rows: 12, four each on 2025-01-01, 2025-07-01 and 2026-01-01. Backward timestamp steps: 0. Blank values: 0.
- Aggregate decoded SHA-256, over samples in date order: `3bffe84e6b861e124c30399c134be0f56ec5d12bfa87c358ad4ec8825064fa2f`

The local build and the independent byte-for-byte verification both completed successfully against the pinned archives.

## Judge checks

**Gate.** `python3 tools/autocollect/gate.py staging/fingrid_nordic_grid_frequency_10hz_f32` passed with no warnings (93 samples, median 863,917 values, widths [32]).

**Reproducibility.**
- I ran `bash staging/.../verify.sh` myself: `verify=ok samples=93 values=80261336 bytes=321045344 excluded_days=none`, exit 0.
- build.sh reads only the local pinned archives; grep finds no network modules in either Python script.
- The driver's download log shows the current pins validated, with every member's CRC32 matching for 2025-07 and 2026-01.

**Bytes.** I decoded 7 samples in full with `struct` and scanned all 93:
- Values: daily means 49.990–50.007 Hz, standard deviations 0.021–0.053 Hz, median absolute step 0.38–0.72 mHz.
- The lag-1 autocorrelation of the steps is negative on every inspected day (-0.20 to -0.39).
- Every value has the same float32 exponent; 14k–37k distinct values per day; all 93 sample hashes are distinct.

**Single chain.**
- The share of values on the 1 mHz lattice is 0.86–1.14% per hour-sized block.
- The worst 5-minute window across all 93 days is 1.8%.
- The longest run of consecutive 1 mHz-lattice values on any day is 4.

So there are no backup-chain stretches, including ones short enough to slip under the day-level threshold.

**Independent decoder.**
- bsdtar extracted 2025-07-13 and 2025-07-31, two days not among the builder's cross-checks.
- Sizes and CRC32s matched `members.tsv`.
- My own naive parser reproduced both samples byte-for-byte.
- The spikes (for example 50.3877 Hz at 2025-07-31 14:50:42.500) are present in the published CSV.

**Documentation.** The README's gap, duplicate and coverage figures, and the aggregate SHA-256 recomputed in date order, match the index exactly.

**Rights.** I read the cached dataset page JSON. Dataset 339 is under CC BY 4.0, and its listing contains the three pinned links with matching sizes. The scripts contain no credentials, and the recipe contains no personal data.

**Novelty.** `novelty.py` (Fingrid URL plus terms fingrid, grid frequency, taajuus, mains frequency, system frequency, nordic synchronous) matched only this candidate. The nearest neighbours are electricity load and PMU voltage magnitude, both different quantities.

**Housekeeping.** `.data/downloads/<id>/` still holds the 2024-01 and 2024-07 archives from the first revision (about 131 MB). build and verify ignore them, and they can be removed as generated scratch.
