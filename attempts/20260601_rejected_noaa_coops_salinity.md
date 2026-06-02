# noaa_coops_salinity

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: `noaa_coops_salinity`
- Source: `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=salinity`
- Why it looked promising: public NOAA CO-OPS sensor API, native numeric marine salinity observations, and a source family that already fits the repo’s logging and chunking model.
- Failure class: unsupported product-station selection and downloader false-positive success
- What happened: the chosen two-station subset (`9414290` and `8518750`) returned only NOAA API error payloads stating that no data was found and that the product may not be offered at those stations for the requested time. The copied downloader pattern did not propagate validation failure correctly inside `fetch()`, so the run appeared successful even though all local files are error payloads. `build.sh` then failed on the first file.
- Evidence: `.data/downloads/noaa_coops_salinity/noaa_coops_9414290_san_francisco/noaa_coops_9414290_san_francisco_20220101_20220130.json` contains `{"error":{"message":"No data was found. This product may not be offered at this station at the requested time."}}`.
- Logs:
  - `.data/logs/noaa_coops_salinity/download.latest.log`
  - `.data/logs/noaa_coops_salinity/build.latest.log`
- Decision: do not accept this recipe under `datasets/`. Track it here and remove the recipe directory from the accepted set.
- Retry conditions: retry only after identifying a station subset that actually serves `product=salinity` across the target date range and preserving the stricter downloader validation that rejects NOAA API error payloads before they are cached.
