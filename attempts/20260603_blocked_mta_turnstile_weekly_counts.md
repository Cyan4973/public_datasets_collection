Status: blocked

Dataset ID: `mta_turnstile_weekly_counts`

Summary:
- attempted a new operational transport dataset based on public MTA turnstile weekly files
- staged recipe targeted pinned weekly files from `2024-01-06` through `2024-03-30`
- user-ran downloads failed uniformly with `404` across both tried host variants

Tried source paths:
- `https://www.mta.info/developers/data/nyct/turnstile/turnstile_<YYMMDD>.txt`
- `https://web.mta.info/developers/data/nyct/turnstile/turnstile_<YYMMDD>.txt`

Observed failure:
- all 13 pinned weekly files returned `404`
- no payloads were downloaded
- downloader validation and fallback host logic were not the problem; the public file path pattern appears to have drifted or the source is no longer exposed at the expected location

Why blocked:
- this environment cannot reliably inspect the current live MTA turnstile publication layout because the relevant hosts are filtered on the agent network path
- without a verified public file listing or a known-correct local archive, further retries would just repeat blind 404s

What would unblock it:
- a verified current MTA turnstile file URL pattern
- or a local copy of the intended weekly files

Notes:
- this is a source-path/access blocker, not a parser or numeric-format blocker
- if the correct current publication path is discovered later, the recipe can be restaged quickly
