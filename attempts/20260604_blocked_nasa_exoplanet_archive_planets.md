Status: blocked

Dataset ID: `nasa_exoplanet_archive_planets`

Summary:
- attempted a new astronomy catalog recipe based on a pinned NASA Exoplanet Archive TAP CSV query over `pscomppars`
- kept the recipe in `staging/` as intended by the new workflow
- repeated user-run download attempts failed with HTTP `400`

What was tried:
- shorthand TAP form:
  - `.../TAP/sync?query=...&format=csv`
- explicit TAP form:
  - `.../TAP/sync?query=...&format=csv&lang=ADQL&request=doQuery`
- query URL encoding and SQL spacing were corrected between attempts

Observed failure:
- endpoint remained reachable but rejected the request with `400`
- no payload was downloaded
- current downloader does not capture a useful server-side error body, so additional blind query edits would not be disciplined

Why blocked:
- the current TAP query contract for this endpoint is not verified from this environment
- continuing to guess at ADQL or endpoint parameters without a returned error body is low-quality iteration

What would unblock it:
- a verified working TAP query example for the current Exoplanet Archive endpoint
- or a local saved CSV export for the intended query shape

Evidence:
- `.data/logs/nasa_exoplanet_archive_planets/download.latest.log`
- `.data/downloads/nasa_exoplanet_archive_planets/download_failures.tsv`
