# Census ACS 1-Year State Population Annual

Status: `blocked`

## Summary

Rejected from the batch because the Census API responded with an HTML `Missing Key` page instead of JSON data for the unauthenticated ACS requests.

## Dataset Idea

- source family: U.S. Census ACS API
- source shape: yearly JSON table responses
- intended output: one annual state population sample per state plus aligned year arrays

## What Was Tried

- queried yearly ACS 1-year endpoints for `2015..2023`
- fixed variable: `B01003_001E`
- no API key provided

## Failure

- the download responses were HTML pages stating `A valid key must be included with each data API request`
- the initial downloader validation incorrectly treated those responses as successful downloads
- `build.sh` then failed while trying to parse the cached HTML as JSON

## Evidence

- download log: `.data/logs/census_acs1_state_population_annual/download.latest.log`
- build log: `.data/logs/census_acs1_state_population_annual/build.latest.log`

## Reason For Non-Acceptance

- the current acquisition path is blocked by an API key requirement
- the downloader must not accept HTML error pages as valid JSON payloads

## Retry Conditions

- either provide an approved public key workflow for Census API access, or choose a public Census access path that does not require a key
- fix downloader validation so non-JSON error pages are rejected immediately
