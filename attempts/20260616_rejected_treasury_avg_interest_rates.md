# treasury_avg_interest_rates

- Date: 2026-06-16
- Status: rejected
- Candidate dataset: U.S. Treasury average interest rates table
- Source: `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates`
- Why it looked promising: Stable U.S. Treasury Fiscal Data table with a native percentage field and public pagination.
- Failure class: fully_exhausted_source_below_floor
- What happened: The accepted recipe was a first-page slice with `400` primary values, `800` primary bytes, and median sample size `100`. A repair review found the API metadata reports only `4,961` total table rows across `50` pages at the old page size.
- Why more download does not save this recipe: The only real compression-target field is `avg_interest_rate_amt`. Calendar year/month/day and similar date decomposition fields are helper/alignment metadata and must not count toward acceptance. Exhausting the full table would therefore yield only `4,961` primary rate values, below the `10,000` primary-value floor and far below the `100 KB` primary-byte floor.
- Evidence: Cached API metadata in `.data/downloads/treasury_avg_interest_rates/avg_interest_rates.json` reported `meta.total-count = 4961` and `meta.total-pages = 50`.
- Decision: Remove `treasury_avg_interest_rates` from `datasets/`; do not repair by counting calendar helper fields or by mixing unrelated Treasury Fiscal Data tables.
- Retry conditions: Retry only if a materially larger, homogeneous Treasury rate table is identified where native non-helper primary fields clear the acceptance floor.
