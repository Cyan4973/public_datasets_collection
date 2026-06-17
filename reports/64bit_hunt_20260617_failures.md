# 64-bit Hunt Download Failures - 2026-06-17

## `usdot_bts_ontime_2024_q1_f64`

Initial download result: failed.

Observed local failure file:

```text
resource	status	detail
On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2024_1.zip	failed	curl_failed
On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2024_2.zip	failed	curl_failed
On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2024_3.zip	failed	curl_failed
```

Observed log reason: each generated Reporting Carrier URL returned HTTP 404.

First repair action attempted:

- Updated `staging/usdot_bts_ontime_2024_q1_f64/download.sh` to try the
  likely BTS Marketing Carrier filename family first:
  `On_Time_Marketing_Carrier_On_Time_Performance_(Beginning_January_2018)_2024_<month>.zip`.
- Kept the original Reporting Carrier filename as an explicit fallback.
- Updated the manifest to describe the Marketing Carrier material rather than
  the older Reporting Carrier file family.

Second download result: failed.

Observed local failure file after the retry:

```text
resource	status	detail
On_Time_Marketing_Carrier_On_Time_Performance_(Beginning_January_2018)_2024_1.zip	failed	curl_failed primary=https://transtats.bts.gov/PREZIP/On_Time_Marketing_Carrier_On_Time_Performance_(Beginning_January_2018)_2024_1.zip fallback=https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2024_1.zip
On_Time_Marketing_Carrier_On_Time_Performance_(Beginning_January_2018)_2024_2.zip	failed	curl_failed primary=https://transtats.bts.gov/PREZIP/On_Time_Marketing_Carrier_On_Time_Performance_(Beginning_January_2018)_2024_2.zip fallback=https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2024_2.zip
On_Time_Marketing_Carrier_On_Time_Performance_(Beginning_January_2018)_2024_3.zip	failed	curl_failed primary=https://transtats.bts.gov/PREZIP/On_Time_Marketing_Carrier_On_Time_Performance_(Beginning_January_2018)_2024_3.zip fallback=https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2024_3.zip
```

Observed log reason: primary and fallback URLs all returned HTTP 404.

Current status: rejected for this hunt. Do not retry the BTS candidate without
exact verified archive URLs or a different official BTS extraction path.

## `sec_fsd_2024q1_q4_numeric_values_i64`

Initial download result: false semantic failure.

Observed reason: the script required a `num.tsv` member, but the official SEC
Financial Statement Data Sets ZIPs contain `num.txt`.

Repair action applied:

- Updated download validation to accept `num.txt` or `num.tsv`.
- Updated the shared builder to read `num.txt` or `num.tsv`.
- Re-ran download validation against local cached ZIPs, then build and verify.

Current status: validated successfully.

Material state:

- source bytes: `484,669,724`
- primary samples: `8`
- primary values: `11,808,107`
- primary bytes: `94,464,856`
- median primary sample values: `1,379,016.5`
