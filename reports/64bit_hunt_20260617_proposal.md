# 64-bit Hunt Proposal - 2026-06-17

Scope: new 64-bit numeric candidates plus local unfinished 64-bit repair audit.
No dataset payloads were downloaded during this hunt. Scripts were staged for the
user to run.

## Local Unfinished Audit

The unfinished 64-bit staging list is mostly not repairable without violating the
median natural-sample floor:

| dataset_id | decision | material state |
|---|---|---|
| `ena_runs_portal` | reject for now | Existing output has one 64-bit sample of only 500 values and is redundant with accepted `ena_portal_search`. |
| `sec_companyfacts_core_financials_quarterly` | reject in current shape | Natural samples are issuer-fact quarterly series with only 32-51 values. Adding issuers/facts would multiply tiny natural samples, not repair the median floor. |
| `sec_submissions_nvda` | reject/superseded | Single issuer, about 1,002 filings per column, below aggregate byte/value floor and superseded by broader SEC submissions work. |
| `sec_submissions_tsla` | reject/superseded | Same issue as NVDA: single issuer and below floor. |
| `usgs_water_current` | technically passes, low priority | Local output passes current floors, but it is a single-site USGS instantaneous water time series and overlaps the already large USGS NWIS family. |

Detailed numeric state is in `reports/unfinished_64bit_staging_state.md` and
`reports/unfinished_64bit_staging_state.tsv`.

## Staged Candidate Set

| dataset_id | source | license status | material / shape | why this is not just more of the same | expected scale |
|---|---|---|---|---|---|
| `citibike_2024_01_trip_geocoords_f64` | Citi Bike January 2024 tripdata ZIP | Existing accepted source scope, `LicenseRef-Citi-Bike-System-Data` | Trip-level start/end latitude and longitude as four native float64 table columns. Natural sample is one monthly trip table column. | Existing Citi Bike recipe kept only station-id dictionary codes. This keeps continuous trip geocoordinates from operational mobility records. | Source ZIP 369 MB. Expected output about 4 columns x about 1.9M values x 8 bytes, roughly 60 MB. |
| `usdot_bts_ontime_2024_q1_f64` | U.S. DOT BTS TranStats PREZIP monthly on-time performance files | U.S. Government Work | Flight-operation delay, taxi, air-time, and distance columns as float64, one sample per month-column. | Aviation operations would be novel, but this candidate is rejected for now. | Rejected: both attempted public filename families returned HTTP 404 for all three selected months. Do not retry without exact verified URLs. |
| `census_acs_pums_ca_person_2023_i64` | U.S. Census ACS 2023 1-year California PUMS person file | U.S. Government Work | Person-level public-use microdata columns: person weight, personal income, wage income, weeks worked as int64. | Microdata/person-record tables are materially different from the existing tiny Census aggregate indicator recipes. | One state ZIP; expected output roughly tens of MB, well below 1 GB. |
| `sec_fsd_2024q1_q4_numeric_values_i64` | SEC Financial Statement Data Sets quarterly `num.txt` files | U.S. Government Work | Broad public-company XBRL numeric fact table values split into USD and shares int64 streams, one sample per quarter-unit column. | This is a real repair/replacement path for the thin SEC companyfacts standalones; it uses official table-level quarterly fact files instead of tiny per-company time series. | Four quarterly ZIPs; expected output tens to low hundreds of MB, below 1 GB. |

## Runbook

Download stage for the user:

```bash
failed=0
for d in \
  citibike_2024_01_trip_geocoords_f64 \
  census_acs_pums_ca_person_2023_i64 \
  sec_fsd_2024q1_q4_numeric_values_i64
do
  if ! bash "staging/$d/download.sh"; then
    echo "FAILED download: $d"
    failed=1
  fi
done
echo "download_failed=$failed"
```

Processing stage after downloads complete:

```bash
failed=0
for d in \
  citibike_2024_01_trip_geocoords_f64 \
  census_acs_pums_ca_person_2023_i64 \
  sec_fsd_2024q1_q4_numeric_values_i64
do
  if ! bash "staging/$d/build.sh"; then
    echo "FAILED build: $d"
    failed=1
    continue
  fi
  if ! bash "staging/$d/verify.sh"; then
    echo "FAILED verify: $d"
    failed=1
  fi
done
echo "processing_failed=$failed"

python3 tools/report_dataset_state.py \
  --output-md reports/64bit_hunt_20260617_state.md \
  --output-tsv reports/64bit_hunt_20260617_state.tsv \
  staging/citibike_2024_01_trip_geocoords_f64 \
  staging/census_acs_pums_ca_person_2023_i64 \
  staging/sec_fsd_2024q1_q4_numeric_values_i64
```

## Notes

- `staging/` is ignored by git in this repository. If any candidate is accepted
  after successful download/build/verify, promote it to `datasets/` or force-add
  the staging recipe explicitly.
- Download scripts do semantic checks before success: ZIP readability and
  required source columns/members. Build scripts enforce current floors and the
  1 GB primary-output cap.
