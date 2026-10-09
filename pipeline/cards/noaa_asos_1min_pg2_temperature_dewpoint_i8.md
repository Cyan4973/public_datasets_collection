# NOAA/NWS/FAA ASOS One-Minute Page-2 Observations (DSI 6406): 1-Minute Air Temperature and Dew Point (integer °F) Int8

- Candidate id: `noaa_asos_1min_pg2_temperature_dewpoint_i8`
- Width: int8
- Quantity: 1-minute ASOS dry-bulb air temperature and dew-point temperature in whole degrees Fahrenheit (the last two fields of each DSI 6406 page-2 record), signed, about -40..+120.
- Source: https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg2/
- Resources: https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg2/access/2024/, https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg2/doc/asos-1min-pg2_documentation.pdf, https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncdc:C00387/xml
- License: U.S. Government public domain (NWS/FAA/DoD/NCEI federal work; 17 U.S.C. 105). Same basis as the accepted noaa_isd_lite recipe.
- License evidence: https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncdc:C00387/xml
- License quote: NCEI ISO record gov.noaa.ncdc:C00387 ('1-Minute Page 2 Surface Weather Observations from the ASOS Network') carries only 'Cite as: NOAA National Weather Service, U.S. Federal Aviation Administration, U.S. Department of Defense, NOAA National Centers for Environmental Information (2005) ... NCEI DSI 6406_02' plus NOAA distribution/use-liability disclaimers; no use restriction.
- Natural record: One station-month file asos-1min-pg2-<ICAO>-YYYYMM.dat (up to 44,640 one-minute rows). One sample per station-month per series (temperature series, dew-point series).
- Estimated samples: 360
- Estimated primary values: 31,000,000
- Estimated download bytes: 1,350,000,000
- Estimated primary bytes: 31,000,000
- Decode path: Pure stdlib text parsing of fixed-format lines (WBAN+ICAO, call, local date-time + UTC, precip id/amount, 3 pressure sensors, temp, dewpoint). Take the last two integer fields as temperature and dew point and pack as int8. Reject the sample (or choose another station) if any value is outside -128..127. Skip rows with missing/'M' fields and log the counts.
- Novelty kind: new_source
- Measurement type: met_station_obs
- Instrument line: asos_hygrothermometer_1min
- Archive collection: www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg2
- Novelty evidence: novelty.py --url .../automated-surface-observing-system-one-minute-pg2/access/ --terms ASOS one-minute dewpoint: no URL matches and no ASOS 1-min in the registry or ledger. GHCN-Daily recipes are daily aggregates from other files at 16 bits, ISD-lite is hourly tenths-°C int16, and appliances dewpoint is f32/f64. No minute-resolution surface temperature at 8 bits exists.
- Homogeneity: One instrument system (ASOS hygrothermometer), one product (DSI 6406 page 2), one unit (integer °F) and a 1-minute lattice. Use a pinned list of about 30 climatically spread ASOS stations x 12 months of 2024. Temperature and dew point are separate series. All samples share a scale; no mixing of °C sources.
- Risks: Extraction ratio is about 2 of 12 fields (about 1.5-2% of bytes kept), giving roughly 31 MB of primary from roughly 1.35 GB. The int8 range could be exceeded by extreme desert heat (>127 °F); pick stations accordingly and validate. Minute gaps and maintenance periods break the lattice. Probe distance between temperature and dew point is 0.042 (same recipe, fine). It may be compression-similar to other smooth small-integer series (nearest feature families: household power HVAC 0.080, MIT-BIH V4 0.101, Scotland scan angle 0.077-0.104). Possible overlap concern with the ASOS page-1 wind candidate (separate DSI product and quantity; feature distance 0.118).
- Probe evidence: Directory 2024/07 lists 877 station files; KDEN 202401 pg2 HEAD Content-Length 3,680,184; range GETs return 206. Parsed the first 3 MB of KORD 202407 (26,548 rows, T 54..91 °F) and KDEN 202401 (26,541 rows, T -13..56 °F). zlsim feature probe nearest: KORD T 0.080 (power_hvac), KDEN T 0.101 (mitbih_v4), KDEN Td 0.077 (Scotland scan angle i8). All above 0.05.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_101019.jsonl`).
