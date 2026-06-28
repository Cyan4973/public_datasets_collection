# NVD CPE Match Feed

NVD CPE Match Criteria API records. The recipe paginates the feed and keeps
homogeneous numeric columns from each match-string record: timestamp fields as
Unix epoch seconds and the attached CPE-name match count.

Source URL template:
- `https://services.nvd.nist.gov/rest/json/cpematch/2.0?resultsPerPage={resultsPerPage}&startIndex={startIndex}`

Selected series:
- `nvd_cpe_last_modified_at_u32`
- `nvd_cpe_cpe_last_modified_at_u32`
- `nvd_cpe_match_count_u16`

Download knobs:
- `NVD_CPE_MATCH_PAGE_SIZE` defaults to `500`, the conservative API limit.
- `NVD_CPE_MATCH_MAX_RECORDS` defaults to `10000`.
- `NVD_CPE_MATCH_MIN_RECORDS` defaults to `5000`.
- `NVD_CPE_MATCH_REQUEST_DELAY_SECONDS` defaults to `6`.
- `NVD_API_KEY` is optional and is sent as an API key header when set.

Build knobs:
- `NVD_CPE_MATCH_MIN_RETAINED_RECORDS` defaults to `5000`.
