# noaa_coops_conductivity

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: `noaa_coops_conductivity`
- Source: `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=conductivity`
- Why it looked promising: public NOAA CO-OPS sensor API, native numeric marine water-quality observations, and a source family with several prior successes in this repo.
- Failure class: unsupported product-station selection and downloader false-positive success
- What happened: the chosen two-station subset (`9414290` and `8518750`) returned only NOAA API error payloads stating that no data was found and that the product may not be offered at those stations for the requested time. The copied downloader pattern did not propagate validation failure correctly inside `fetch()`, so every failed chunk was still counted as successful. `build.sh` then failed immediately on the first raw file.
- Evidence: `.data/downloads/noaa_coops_conductivity/noaa_coops_9414290_san_francisco/noaa_coops_9414290_san_francisco_20220101_20220130.json` contains `{"error":{"message":"No data was found. This product may not be offered at this station at the requested time."}}`.
- Logs:
  - `.data/logs/noaa_coops_conductivity/download.latest.log`
  - `.data/logs/noaa_coops_conductivity/build.latest.log`
- Decision: do not accept this recipe under `datasets/`. Track it here and remove the recipe directory from the accepted set.
- Retry conditions: retry only after identifying a station subset that actually serves `product=conductivity` across the target date range and keeping the stricter downloader validation in place.
