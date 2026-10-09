# USDA NRCS SNOTEL Network Hourly Ultrasonic Snow Depth (integer inches) per Station-Water-Year, UInt8

- Candidate id: `nrcs_snotel_hourly_snow_depth_u8`
- Width: uint8
- Quantity: Hourly snow depth in whole inches from the ultrasonic depth sensors at SNOTEL sites in the western US and Alaska (element SNWD, hourly, start-of-period value).
- Source: https://www.nrcs.usda.gov/wps/portal/wcc/home/
- Resources: https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customMultipleStationReport/daily/start_of_period/network=%22SNTL%22%7Cname/0,0/stationId,state.code,elevation, https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customSingleStationReport/hourly/start_of_period/1050:CA:SNTL%7Cid=%22%22%7Cname/2024-01-01,2024-12-31/SNWD::value, https://catalog.data.gov/dataset/snowpack-telemetry-network-snotel
- License: Public domain (US Government work, USDA NRCS)
- License evidence: https://catalog.data.gov/dataset/snowpack-telemetry-network-snotel
- License quote: data.gov entry 'SNOwpack TELemetry Network (SNOTEL)', publisher NRCS (Department of Agriculture): License "https://www.usa.gov/publicdomain/label/1.0/", Access Level "public".
- Natural record: One station x one water year (Oct 1 - Sep 30) of hourly SNWD values. Missing hours are dropped (an optional auxiliary hour-offset series keeps alignment). One sample per station-water-year.
- Estimated samples: 2,400
- Estimated primary values: 17,000,000
- Estimated download bytes: 460,000,000
- Estimated primary bytes: 17,000,000
- Decode path: download.sh fetches the SNTL station list CSV, then one reportGenerator CSV per station covering WY2022-WY2024 (curl, rate-limited with retries). Stdlib Python skips '#' lines, parses 'Date,Snow Depth (in)' rows and int(float(value)) non-empty values, splits by water year, and writes uint8. Station-years with any value outside 0-255, or with fewer than about 1,000 valid hours, are excluded, never clamped.
- Novelty kind: new_source
- Measurement type: met_station_obs
- Instrument line: nrcs_snotel_ultrasonic_snow_depth
- Archive collection: wcc.sc.egov.usda.gov
- Novelty evidence: novelty.py --url https://wcc.sc.egov.usda.gov/reportGenerator/ --terms snotel 'snow depth' nrcs: no URL, recipe, registry or ledger matches. The only hit is downstream ghcn_snwd (GHCN Daily snow depth, 16-bit daily mm), a different network, cadence and unit. No local snow-depth family; no same-archive recipes. zlsim feature probe on 5,680 hourly values (1050:CA, 2024): nearest openf1_throttle 0.092, hc18 ultrasound 0.099, aegis OBD 0.106. The accepted RH/temperature/wind u8 station families are not among the nearest.
- Homogeneity: One network (SNOTEL), one sensor class (ultrasonic depth), one element (SNWD), one unit (integer inches), hourly cadence, contiguous WY2022-2024. Exclude SCAN, SNOLITE, snow-course and daily-duration series.
- Risks: (1) The AWDB REST API returns 403 here. The reportGenerator CSV endpoint works but needs about 900 per-station requests with rate limiting and retries. (2) Many missing summer hours (station 1050 lost about 35% of 2024, mostly June-October), and snow-free periods are genuine zeros (1,131 of 5,680 at 1050). Low-elevation stations may approach zero-dominance, so verify should report mode share. (3) Ultrasonic spikes in provisional, not fully QC'd hourly data. (4) Not every one of the 934 stations has hourly SNWD (1085:CA returned none), so realized sample count must be reported, not claimed. (5) Paradise WA peaked at 202 in WY2023; drop out-of-range station-years. (6) Slowly varying integer series, similar in kind to the accepted RH/temperature u8 families, though the probe did not place them nearest.
- Probe evidence: SNTL station list CSV: 934 stations. Hourly SNWD CSVs: 1050:CA 2024 = 5,680 values, 0-221; 838:CO 2024 = 8,266 rows; 679:WA WY2023 = 6,340 values, max 202; 909:WA WY2023 = 7,890 values, max 138, none out of range. data.gov confirms the public-domain label. Total transfer under 1 MB.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_114820.jsonl`).
