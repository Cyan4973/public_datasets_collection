# world_bank_co2_emissions_per_capita_annual

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: `world_bank_co2_emissions_per_capita_annual`
- Source: `https://api.worldbank.org/v2/country/<ISO3>/indicator/EN.ATM.CO2E.PC?format=json&per_page=20000`
- Why it looked promising: public World Bank indicator API, country-level annual numeric series, and a source family that already worked elsewhere in this repo.
- Failure class: invalid upstream indicator and download validation bug
- What happened: the selected indicator id `EN.ATM.CO2E.PC` currently returns an API error payload stating that the indicator was not found. The recipe downloader logged the validation failure but still treated each fetch as successful, so the local files contain error JSON instead of indicator rows. `build.sh` then failed when it assumed the normal two-element World Bank payload shape.
- Evidence: `.data/downloads/world_bank_co2_emissions_per_capita_annual/USA.json` contains `{"message":[{"id":"175","key":"Invalid format","value":"The indicator was not found. It may have been deleted or archived."}]}`.
- Logs:
  - `.data/logs/world_bank_co2_emissions_per_capita_annual/download.latest.log`
  - `.data/logs/world_bank_co2_emissions_per_capita_annual/build.latest.log`
- Decision: do not accept this recipe under `datasets/`. Track it here and remove the broken recipe directory.
- Retry conditions: retry only after identifying a currently valid World Bank CO2-related indicator id and tightening the World Bank downloader pattern so API error payloads are rejected before the files are accepted into cache.
