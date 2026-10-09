# NOAA ASOS one-minute page-2 temperature and dew point int8 development

## Outcome

Accepted `noaa_asos_1min_pg2_temperature_dewpoint_i8`. It provides 1-minute ASOS dry-bulb air temperature and dew-point temperature in whole degrees Fahrenheit, stored as native signed int8. There is one sample per station-month per series.

The recipe is distinct from the accepted `noaa_asos_1min_pg1_wind_speed_u8`:

| | pg1 (accepted) | pg2 (this recipe) |
| --- | --- | --- |
| NCEI product | DSI 6405 | DSI 6406 |
| Files | pg1 station-month files | separate pg2 files |
| Sensor | wind sensor | hygrothermometer |
| Quantity | wind speed, knots | temperature and dew point, °F |
| Year | 2024 | 2022 |

It also differs from the existing temperature families in cadence and width:
- GHCN-Daily: daily, 16-bit;
- ISD-lite: hourly, int16, tenths °C;
- CO-OPS: 6-minute, float64.

No local or downstream family carries minute-cadence station temperature at 8 bits. Measured breadth is OK: the nearest family is USCRN 5-minute RH u8 at 0.0757 for temperature, and downstream power_hvac at 0.0792 for dew point.

## Source and rights

- Source: NOAA NCEI "1-Minute Page 2 Surface Weather Observations from the ASOS Network" (DSI 6406, ISO record `gov.noaa.ncdc:C00387`). Files come from `https://www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg2/access/2022/MM/`.
- Pinned selection: 509 station-month `.dat` files, 2,400,428,490 bytes. Exact sizes and listing timestamps are in `sources.tsv`, which `discover.sh` can regenerate from directory listings.
- Selection rule: 44 stations, kept when the listed size is at least 80% of a complete month. This skips 19 of 528 station-months.
- Documentation: `asos-1min-pg2_documentation.pdf` (2022-11-08), SHA-256 `e534851592b80bb157ad5c2350cbe8f5ac2f8778e01b69d93a66dba9f2764d46`.
- License: U.S. Government public domain, as a federal work of NWS, FAA, DoD and NCEI (17 U.S.C. 105). The ISO record's only `otherConstraints` texts are a citation request and two liability disclaimers. It contains no use restriction.

## Shape and conversion

Each natural record is one fixed-width ASCII station-month file: 112 characters plus LF per line, one line per minute in LST. The temperature slot is 0-based columns 93-97 and the dew-point slot is columns 98-102. The PDF confirms the fields as "Average 1-minute dry bulb temperature (Deg F)" and "Average 1-minute dew point temperature (Deg F)".

Values are written unchanged as int8 in file (time) order. The following are dropped and counted:
- missing slots (`[ M ]`, `M`, blank);
- bracketed values, an undocumented marker affecting 0.13% of temperature and 0.20% of dew-point rows;
- values outside -128..127 (72 dew-point glitches);
- malformed rows (1,059 of 21,242,730);
- repeated LST minutes after the first row (53,428).

A content rule then excludes any station-month in which either series is valid for less than 80% of the month's minutes. This removes 9 station-months: KDTW 03-05, KEYW 04 and 07, KINL 12, PATO 11-12 and PHNL 11. Nothing is imputed, so a sample is the sequence of valid minutes, not a gap-filled lattice.

NCEI does not edit these data. In-range glitches are therefore kept as recorded: 704 dew-point values above 90 °F (0.003%, mostly PATO) and one -78 °F temperature at KMSP 2022-08.

## Accepted output

| series | samples | values = bytes | min / median / max values per sample | range | max / median mode share |
| --- | --- | --- | --- | --- | --- |
| `air_temperature_degf_i8` | 500 | 20,775,709 | 33,562 / 42,157 / 44,588 | -78..117 °F | 0.180 / 0.051 |
| `dew_point_temperature_degf_i8` | 500 | 20,763,794 | 33,384 / 42,020 / 44,588 | -68..127 °F | 0.319 / 0.069 |

- Total primary: 1,000 samples, 41,539,503 bytes.
- Stations: 44. Partial years: TJSJ 6 months, PANC 7, PAFA 8, KDTW and PAJN 9, KEYW and PATO 10, KINL, KLAS and PHNL 11. All other stations have 12.
- Download: 2,400,428,490 bytes. Extraction is 1.7% because NCEI offers no field-projected access, the same ratio as the accepted pg1 sibling.

## Judge checks

- `python3 tools/autocollect/gate.py staging/noaa_asos_1min_pg2_temperature_dewpoint_i8`: PASS, no warnings. It reports 41,539,503 values, 1,000 samples, median 42,125 and width 8.
- `bash staging/.../verify.sh`, run by the judge: verify ok in 79 s. Its independent regex parser reproduced every sample byte and sha256, the stored-int8 min/max, every ingest count, the excluded set of 9 station-months, and the manifest totals.
- build.sh reads only `.data/downloads`. `scripts/asos_pg2.py` imports no network modules, and all network I/O is curl in `download.sh` and `discover.sh`. No credentials appear anywhere.
- Byte inspection of 10 station-months per series gave climatically correct ranges:
  - KPHX July: 78..117 °F, mean 97;
  - PAFA January: -47..43;
  - KMIA August: 73..97;
  - TJSJ March: 70..86.
- Other byte checks:
  - 66-88% of deltas are zero, and delta entropy is 0.65-1.5 bits;
  - no duplicate sha256 among the 1,000 samples;
  - LST stamps are monotonic, and duplicate minutes are only consecutive.
- A raw-file scan traced the 79 dew points above 127 to sensor glitches, mainly a daily 23:33 LST spike at TJSJ-03 (128-137 °F). Dew point exceeds temperature in 0.28% of paired rows. Both are unedited source behaviour, and the documentation says "No attempt to edit data".
- License: the judge read the saved ISO record's constraint texts directly. It holds a citation request and two liability disclaimers only.
- Novelty:
  - `novelty.py --url/--terms`: no other recipe uses the pg2 archive.
  - `--type/--instrument/--archive`: same instrument line 0, same archive 0.
  - `--list-width 8`: no 8-bit station temperature family. ISD-lite's 8-bit series are calendar helpers only.
  - Label: `new_content_same_modality`, because station temperature and the ASOS 1-minute program already exist in the corpus.
