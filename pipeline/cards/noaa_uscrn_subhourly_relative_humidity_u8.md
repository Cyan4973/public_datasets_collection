# NOAA U.S. Climate Reference Network (USCRN) Subhourly 5-Minute Relative Humidity (integer %, 2024 station-years) UInt8

- Candidate id: `noaa_uscrn_subhourly_relative_humidity_u8`
- Width: uint8
- Quantity: Relative humidity (%) at 1.5 m, 5-minute values as archived by NCEI in integer percent (field 16 RELATIVE_HUMIDITY of the subhourly01 product), 0-100.
- Source: https://www.ncei.noaa.gov/pub/data/uscrn/products/subhourly01/
- Resources: https://www.ncei.noaa.gov/pub/data/uscrn/products/subhourly01/2024/, https://www.ncei.noaa.gov/pub/data/uscrn/products/subhourly01/readme.txt, https://www.ncei.noaa.gov/pub/data/uscrn/products/subhourly01/HEADERS.txt, https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncdc:C00546/xml
- License: U.S. Government public domain (NOAA/NCEI work; 17 U.S.C. 105). Same basis as the accepted noaa_isd_lite recipe.
- License evidence: https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncdc:C00546/xml
- License quote: NCEI ISO record gov.noaa.ncdc:C00546 (USCRN Quality Controlled Datasets) lists only a citation request ('Cite as: Palecki, M.A., ... (2013): U.S. Climate Reference Network Products ... doi:10.7289/V5H13007') and NOAA distribution/use-liability disclaimers ('NOAA and NCEI make no warranty ...'), with no use restriction; NOAA/NCEI data products are public U.S. government works.
- Natural record: One station-year file CRNS0101-05-2024-<station>.txt (105,408 five-minute rows). One sample = the valid RH series of that station-year in time order.
- Estimated samples: 120
- Estimated primary values: 12,000,000
- Estimated download bytes: 1,700,000,000
- Estimated primary bytes: 12,000,000
- Decode path: Pure stdlib text parsing: whitespace-split fixed-width lines; field 16 is RELATIVE_HUMIDITY (int) and field 17 is RH_FLAG. Keep rows with RH_FLAG == 0 and 0 <= RH <= 100 (missing = -9999; AK winter rows show -1 with flag 3), and emit uint8 in time order. Document dropped-row counts per sample, or alternatively emit the full lattice with an auxiliary validity mask.
- Novelty kind: new_quantity
- Measurement type: met_station_obs
- Instrument line: uscrn_station_rh_sensor
- Archive collection: www.ncei.noaa.gov/pub/data/uscrn/products/subhourly01
- Novelty evidence: novelty.py --url .../uscrn/products/subhourly01/ --terms USCRN 'relative humidity' 'climate reference network': no URL matches (same host only) and no USCRN in the registry or ledger. Relative humidity exists only as f64/f32 reanalysis or UCI series (nasa_power_daily_humidity, appliances_energy_uci, downstream open_meteo_relative_humidity_f32). Nothing at 8 bits: met_station_obs 8-bit coverage is only bike_sharing_uci/isd_lite calendar fields.
- Homogeneity: One network (identical Vaisala HMP-type RH sensor and aspirated-shield siting at every station), one product version (subhourly01, CRX software), one unit (integer %) and one 5-minute lattice; one year (2024). Prefer CONUS+HI stations (about 120) so the flagged AK winter months do not dominate; alternatively take all 159 and accept shorter AK samples.
- Risks: Extraction ratio is poor: 1 of 23 text columns, about 105 KB of RH per 14 MB file (about 0.75%), so roughly 12 MB is kept from roughly 1.7 GB. That is not an aggregate (raw 5-min observations), but the judge may call the kept signal modest. There is no leaner source: no gzip transfer encoding, and the snapshots are multi-GB zips. Integer RH is the archive's representation (the sensor resolves finer), but it is the native archived value. Flagged/missing rows break the strict 5-min lattice. The NOAA licence is public domain by statute rather than a written licence.
- Probe evidence: HEADERS.txt and readme confirm field 16 RELATIVE_HUMIDITY in %. 2024 directory lists 159 station files; Tucson file HEAD Content-Length 14,230,080; range GET returns 206. Parsed first 4 MB of AZ_Tucson_11_W and NC_Asheville_8_SSW: 29.6k valid RH each (Tucson modes 20-37 %, Asheville 92-96 %). zlsim feature probe nearest: 0.077-0.092 (mod15a2h FPAR, AEGIS OBD PID, MIMIC ABP), i.e. outside the 0.05 redundancy distance. Distance to ASOS 1-min temperature 0.096-0.161 and to ASOS wind 0.111.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_101019.jsonl`).
