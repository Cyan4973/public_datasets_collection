# Rejected: openfda_drug_event

Date: 2026-06-15

Original accepted recipe:

- source: openFDA drug adverse-event endpoint
- scope: first unauthenticated `limit=100` API response
- realized output: 99 kept report rows, 5 series, 495 primary values, 1,683 primary bytes
- audit status: below floor by both aggregate and median-sample criteria

Repair attempt:

- redesigned as a bounded January 2024 adverse-event cohort
- target: 20,000 raw reports, at least 16,000 kept rows, at least 250 KiB primary numeric output
- primary fields: native received/receipt dates, seriousness flags, reaction count, drug count
- auxiliary-only field: `safetyreportid`

Result:

- openFDA returned HTTP 403 on the first bounded search request
- changing the downloader to URL-encode query parameters and send a user agent still returned HTTP 403
- no paged repair payload was downloaded

Decision:

- remove from accepted recipes
- do not keep the original one-page sample; it is an intrinsically tiny slice
- revisit only if a reproducible public route can fetch a bounded cohort without a private API key
