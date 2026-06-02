# CDC COVID New Cases State Daily

Status: `transient_failure`

## Summary

Rejected from the exploratory batch after the CDC Socrata state-query download path returned HTTP 404 for every selected state.

## Dataset Idea

- source family: CDC Socrata
- source shape: per-state CSV API queries
- intended output: one signed daily `new_case` sample per state plus aligned date arrays

## What Was Tried

- queried `https://data.cdc.gov/resource/9mfq-cb36.csv`
- fixed five-state subset: `CA`, `TX`, `FL`, `NY`, `IL`
- selected columns: `submission_date`, `state`, `new_case`

## Failure

- every state query returned HTTP `404`
- the initial `download.sh` had a bug that incorrectly logged these failed fetches as successful downloads, but no raw CSV files were actually written
- `build.sh` then failed because the expected raw files were absent

## Evidence

- download log: `.data/logs/cdc_covid_new_cases_state_daily/download.latest.log`
- build log: `.data/logs/cdc_covid_new_cases_state_daily/build.latest.log`

## Reason For Non-Acceptance

- the acquisition path is not currently reproducible
- the downloader must not be accepted in a state where upstream 404 responses are treated as successful cache entries

## Retry Conditions

- identify a working CDC public endpoint or corrected Socrata query shape for this dataset
- fix `download.sh` to fail hard on missing payload files or 4xx responses
- rerun the corrected downloader from a clean local state before reconsidering acceptance
