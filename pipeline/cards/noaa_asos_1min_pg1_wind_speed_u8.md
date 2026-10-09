# NOAA/NWS/FAA ASOS One-Minute Page-1 Observations (DSI 6405): 2-Minute-Average Wind Speed and 5-Second Peak Gust (integer knots, 1-minute) UInt8

- Candidate id: `noaa_asos_1min_pg1_wind_speed_u8`
- Width: uint8
- Quantity: Wind speed in whole knots at 1-minute cadence from the ASOS sonic/cup anemometer: the 2-minute average wind speed and the 5-second peak wind speed fields of each DSI 6405 page-1 record.
- Source: https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg1/
- Resources: https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg1/access/2024/, https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncdc:C00386/xml
- License: U.S. Government public domain (NWS/FAA/DoD/NCEI federal work; 17 U.S.C. 105). Same basis as the accepted noaa_isd_lite recipe.
- License evidence: https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncdc:C00386/xml
- License quote: NCEI ISO record gov.noaa.ncdc:C00386 ('1-Minute Page 1 Surface Weather Observations from the Automated Surface Observing Systems (ASOS) Network'), a sibling of C00387, which carries only a 'Cite as: NOAA National Weather Service, U.S. Federal Aviation Administration, U.S. Department of Defense, NOAA NCEI ...' request and NOAA distribution/use-liability disclaimers; no use restriction.
- Natural record: One station-month file asos-1min-pg1-<ICAO>-YYYYMM.dat (up to 44,640 one-minute rows). One sample per station-month per series (2-min average speed; 5-s peak gust).
- Estimated samples: 360
- Estimated primary values: 31,000,000
- Estimated download bytes: 1,400,000,000
- Estimated primary bytes: 31,000,000
- Decode path: Pure stdlib text parsing. After the two visibility extinction coefficients with D/N flags, each line has four integers: 2-min avg direction (deg), 2-min avg speed (kt), 5-s peak direction (deg), 5-s peak speed (kt), then an optional RVR token. Take the speed fields as uint8 (validate 0..255), skip malformed/'M' rows (about 0.4% in the probe) and keep time order.
- Novelty kind: new_quantity
- Measurement type: met_station_obs
- Instrument line: asos_wind_sensor_1min
- Archive collection: www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg1
- Novelty evidence: novelty.py found no ASOS one-minute source in recipes, registry or ledger. Wind exists only as GHCN-Daily daily-average AWND/WSFG at 16 bits (different files and cadence). No minute-cadence wind speed at 8 bits in the local or downstream corpus.
- Homogeneity: One sensor system (ASOS wind sensor), one product (DSI 6405 page 1), one unit (integer knots) and one 1-minute lattice. Same pinned station list and months as the pg2 candidate (about 30 stations x 12 months of 2024). Average speed and gust are separate series. Directions (0-360) are excluded: they do not fit u8 natively.
- Risks: Extraction ratio is about 2 of about 10 fields, giving roughly 31 MB from roughly 1.4 GB. Calm periods give long low-value runs, which could raise mode share at sheltered sites, so choose open airport sites. The gust series is less distinct (nearest feature distance 0.067: ENA FASTQ phred) than the average speed series (0.102). The same NCEI ASOS program as the pg2 candidate could be read as a sibling proposal, but it is a separate DSI product, file set, sensor and physical quantity (feature distance to 1-min temperature 0.118).
- Probe evidence: pg1 directory 2024/01 lists 881 station files; KDEN 202401 pg1 HEAD Content-Length 3,871,945. Parsed the first 2.5 MB of KORD 202407: 22,030 valid rows (94 skipped); speed modes 4-8 kt, max 37 kt; gust max 54 kt. zlsim feature probe nearest: speed 0.102 (lora24 RSSI i8), gust 0.067 (ENA FASTQ phred).

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_101019.jsonl`).
