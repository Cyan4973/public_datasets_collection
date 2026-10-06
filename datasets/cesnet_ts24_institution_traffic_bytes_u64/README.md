# CESNET-TimeSeries24 Institution 10-Minute Transmitted Bytes (UInt64)

One little-endian `uint64` time series per institution: the number of bytes
(`n_bytes`) carried by all IP flows of that institution on the Czech CESNET3
research and education ISP backbone in each 10-minute window, over 40 weeks
(2023-10-09 to 2024-07-14). The data come from the institution level of
CESNET-TimeSeries24, which aggregates 66 billion IP flow records (about
3.7 PB of traffic).

## Source and license

- Zenodo record 13382427, DOI 10.5281/zenodo.13382427 (single version,
  published 2024-09-27): <https://zenodo.org/records/13382427>
- License: the record metadata declares `cc-by-4.0` (Creative Commons
  Attribution 4.0 International), with open access. `download.sh` re-checks
  the license id, DOI, and the published size and MD5 of each file against
  the live record JSON.
- Citation requested by the authors: Koumar, J., Hynek, K., Čejka, T. et al.
  *CESNET-TimeSeries24: Time Series Dataset for Network Traffic Anomaly
  Detection and Forecasting.* Scientific Data 12, 338 (2025).
  <https://doi.org/10.1038/s41597-025-04603-x>

Resources (all public, anonymous):

| resource | bytes | identity |
|---|---:|---|
| `institutions.tar.gz` | 479,428,489 | MD5 `ab3e15fb8dc9b7120ddb2318795b6812` (published by Zenodo), SHA-256 `f1125485…6ff2` |
| `times.tar.gz` | 211,467 | MD5 `a03813763e07646ca38f17ffd53e549e`, SHA-256 `f1b0c8e2…1280` |
| record JSON | ~17.6 KB | validated by field; not hash-pinned because it embeds live view and download statistics |

## What is collected

- **Primary** `institution_n_bytes_u64`: one sample per institution from
  `institutions/agg_10_minutes/<id>.csv`, column `n_bytes`, every data row in
  source order. Each sample holds at most 40,298 values, one per window of
  `times/times_10_minutes.csv`.
- **Auxiliary** `institution_id_time_u32`: the `id_time` of each emitted value,
  aligned element for element, so windows missing from the source stay
  identifiable. It does not count toward acceptance.

`identifiers.csv` lists 283 institutions (ids 0..284 with gaps), and every id
has a 10-minute member. For five institutions (148, 260, 267, 279 and 283) the
upstream 10-minute file is header-only, even though their hourly and daily
files have rows. These five yield no sample, so **278 samples are emitted**.
The empty set is pinned in both build and verify; any other header-only member
is fatal.

Excluded on purpose:

- `agg_1_hour` and `agg_1_day`, which re-aggregate the same windows.
- The `institution_subnets` and `ip_addresses` levels, which are different
  entities at different scales.
- Every other column: `n_flows` and `n_packets` are different units; the
  `sum_`/`average_`/`std_` unique-destination statistics are not byte counts;
  the ratios and averages are rounded to 2 decimals.

## Conversion

`build.sh` reads `institutions.tar.gz` once as a stream (`tarfile` mode
`r|gz`) and never assumes member order. In the archive, the hourly files come
before the 10-minute ones. It keeps only members whose names match
`institutions/agg_10_minutes/<digits>.csv`.

In each kept CSV it locates `id_time` and `n_bytes` by header name. All 283
ten-minute members share one 19-column header, `id_time,n_flows,n_packets,`
`n_bytes,sum_n_dest_asn,…,avg_ttl`, the same as the hourly files.

Each field is parsed as an exact decimal integer and packed with `<Q`, or
`<I` for `id_time`. There is no float round trip.

## Missing-value policy (shared by build and verify)

- **Missing windows:** windows with no source row are not imputed. Each sample
  holds the present windows in `id_time` order, and the auxiliary series
  records which windows those are. In total, 756,619 of 278 × 40,298 windows
  are absent (6.7%), mostly in small institutions whose files skip windows.
- **Header-only files:** a header-only 10-minute file yields no sample. Only
  the pinned five above are allowed.
- **Fatal errors:** a present row with a blank, signed, fractional,
  exponent-form, non-ASCII or larger-than-uint64 `n_bytes` or `id_time` stops
  the build. So do wrong field counts, blank lines, carriage returns,
  non-increasing `id_time`, an `id_time` outside 0..40297, and an n_bytes
  series that is constant. None occur in the pinned archive.
- **Zeros:** zero byte counts would be kept, but none occur. The minimum
  value is 72.

## Realized scope

| | |
|---|---:|
| primary samples | 278 |
| primary values | 10,446,225 |
| primary bytes | 83,569,800 |
| auxiliary bytes | 41,784,900 |
| values per sample: min / p10 / median / max | 3,402 / 30,328 / 40,270 / 40,298 |
| samples with the full 40,298 windows | 56 |
| samples with fewer than 10,000 values | 8 |

## Width evidence (honest)

The native type is uint64: `n_bytes` sums IPFIX octet counters, which are
unsigned 64-bit, and no narrower standard integer type holds the data.

| bit length | values | share |
|---|---:|---:|
| ≤ 16 | 876,644 | 8.4% |
| 17–24 | 4,730,123 | 45.3% |
| 25–32 | 4,612,803 | 44.2% |
| 33–40 | 226,655 | **2.17%** |
| > 40 | 0 | 0% |

- **Peaks:** 166 of 278 institutions exceed 2^32 at their peak, so a uint32
  encoding would overflow for 60% of the samples.
- **Per-institution maxima:** p10 1.14e9, p25 2.87e9, median 5.66e9 (about
  1.3 × 2^32), p75 1.06e10, p90 2.18e10, overall max 3.47e11 (39 bits,
  institution 49).
- **Concentration:** values above 2^32 come mostly from the largest
  institutions. Five institutions have more than 50% of their windows above
  2^32 and ten have more than 10%. For the median institution, essentially no
  windows exceed 2^32.
- **Upper bytes:** the top three bytes of every uint64 are always zero, which
  is typical of 64-bit byte counters.
- **Comparison with the card:** the card's hourly probe saw about 21% above
  2^32 because it covered large institutions at 6× coarser resolution. At the
  original 10-minute resolution, across all institutions, the share is 2.17%.

Value diversity is high: the median sample has 99.8% distinct values, and the
lowest is 7% (a small institution with repeated tiny counts).

## Verification

`verify.sh` re-checks the archive's size and MD5. It then re-reads the archive
with a separate parser (the `csv` module plus `array`; it shares no code with
the builder) and re-derives every sample. It compares:

- every output byte;
- the sample-file set against `identifiers.csv` minus the pinned empty set;
- every index field;
- the manifest's `sample_count` and `total_size_bytes`;
- the pinned per-institution row count, first and last `id_time`, min, max,
  count above 2^32, distinct-value count and both SHA-256 digests in
  `expected_samples.tsv`.

It also rejects constant series and output below the repository floors.

The parsers were first self-tested on a synthetic archive with the same
layout: id gaps, missing windows, values of 0 and 2^64−1, an AppleDouble
decoy, hourly and daily decoys, and a header-only member. The output matched
byte for byte, tampered and extra sample files were caught, and all 11
malformed-input cases and an unpinned header-only member failed the build.

## Running

```bash
bash staging/cesnet_ts24_institution_traffic_bytes_u64/download.sh   # ~479.7 MB
bash staging/cesnet_ts24_institution_traffic_bytes_u64/build.sh      # ~25 s
bash staging/cesnet_ts24_institution_traffic_bytes_u64/verify.sh     # ~35 s
```

All scripts honor `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/cesnet_ts24_institution_traffic_bytes_u64/`.
