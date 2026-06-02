# noaa_coops_humidity

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: `noaa_coops_humidity`
- Source: `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=humidity`
- Why it looked promising: public NOAA CO-OPS sensor API, native numeric marine/meteorological observations, and a source family that already worked for water level, air temperature, water temperature, and air pressure.
- Failure class: unsupported product-station selection and downloader false-positive success
- What happened: the chosen two-station subset (`9414290` and `8518750`) returned only NOAA API error payloads stating that no data was found and that the product may not be offered at those stations for the requested time. Because the copied downloader pattern did not propagate validation failure correctly inside `fetch()`, the run was logged as successful even though every chunk was an API error payload. `build.sh` then failed immediately on the first raw file.
- Evidence: `.data/downloads/noaa_coops_humidity/noaa_coops_9414290_san_francisco/noaa_coops_9414290_san_francisco_20220101_20220130.json` contains `{"error":{"message":"No data was found. This product may not be offered at this station at the requested time."}}`.
- Logs:
  - `.data/logs/noaa_coops_humidity/download.latest.log`
  - `.data/logs/noaa_coops_humidity/build.latest.log`
- Decision: do not accept this recipe under `datasets/`. Track it here and remove the recipe directory from the accepted set.
- Retry conditions: retry only after identifying a station subset that actually serves `product=humidity` across the target date range and preserving the fixed downloader validation that rejects NOAA API error payloads instead of accepting them into cache.
