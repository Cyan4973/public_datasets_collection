# NOAA ISD-Lite

This recipe collects a curated subset of NOAA NCEI ISD-Lite hourly weather
observations and converts them into raw numeric samples.

Selected scope:
- 46 stations across multiple climate zones
- years `2021`, `2022`, and `2023`
- one output sample per station per series

Series emitted by `build.sh`:
- `isd_year` (`uint16`, little-endian)
- `isd_month` (`uint8`)
- `isd_day` (`uint8`)
- `isd_hour` (`uint8`)
- `isd_temp` (`int16`, little-endian)
- `isd_dewp` (`int16`, little-endian)
- `isd_slp` (`int16`, little-endian)
- `isd_wdir` (`int16`, little-endian)
- `isd_wspd` (`int16`, little-endian)
- `isd_sky` (`int16`, little-endian)
- `isd_precip1h` (`int16`, little-endian)
- `isd_precip6h` (`int16`, little-endian)

Notes:
- Source format is hourly fixed-width integer text distributed as `.gz` files.
- Multi-year station streams are concatenated in year order while preserving
  source row order within each file.
- `-9999` sentinel values in meteorological fields are preserved.
- Rows with parse errors or wrong field counts are dropped.

Selected stations:

```text
486980-99999 singapore
967490-99999 jakarta
486470-99999 kuala_lumpur
821110-99999 manaus
637400-99999 nairobi
430030-99999 mumbai
484560-99999 bangkok
652010-99999 lagos
911820-22521 honolulu
941200-99999 darwin
411940-99999 dubai
412170-99999 abu_dhabi
722780-23183 phoenix
623660-99999 cairo
943260-99999 alice_springs
725650-03017 denver
442920-99999 ulaanbaatar
846280-99999 lima
037720-99999 london
071570-99999 paris
476710-99999 tokyo
947670-99999 sydney
875760-99999 buenos_aires
837800-99999 sao_paulo
162420-99999 rome
688160-99999 cape_town
724940-23234 san_francisco
722190-13874 atlanta
583620-99999 shanghai
931190-99999 auckland
725300-94846 chicago
716240-99999 toronto
276120-99999 moscow
545110-99999 beijing
471080-99999 seoul
029740-99999 helsinki
024840-99999 stockholm
726580-14922 minneapolis
123750-99999 warsaw
296340-99999 novosibirsk
474120-99999 sapporo
702730-26451 anchorage
702610-26411 fairbanks
040300-99999 reykjavik
012250-99999 tromso
249590-99999 yakutsk
```

Usage:

```sh
bash datasets/noaa_isd_lite/download.sh
bash datasets/noaa_isd_lite/build.sh
bash datasets/noaa_isd_lite/verify.sh
```

Local layout under `${DATA_DIR:-.data}`:
- `downloads/noaa_isd_lite/history/isd-history.csv`
- `downloads/noaa_isd_lite/isd-lite/<year>/<usaf-wban>-<year>.gz`
- `downloads/noaa_isd_lite/download_failures.tsv`
- `filtered/noaa_isd_lite/station_row_counts.tsv`
- `index/noaa_isd_lite/samples.jsonl`
- `logs/noaa_isd_lite/download.latest.log`
- `logs/noaa_isd_lite/build.latest.log`
- `logs/noaa_isd_lite/verify.latest.log`
- `samples/noaa_isd_lite/<series_id>/<station_slug>.bin`

Logging:
- Every script writes timestamped logs under `${DATA_DIR:-.data}/logs/noaa_isd_lite/`.
- Each script also refreshes a stable `*.latest.log` file for the most recent run.
- `download.sh` writes `download_failures.tsv` with one row per failed station-year fetch.

Sample index:
- `build.sh` writes `${DATA_DIR:-.data}/index/noaa_isd_lite/samples.jsonl`.
- The index contains one JSON object per sample file with `dataset_id`,
  `series_id`, `sample_path`, `numeric_kind`, `bit_width`, `endianness`,
  `element_size_bytes`, `sample_size_bytes`, and `value_count`.
- `sample_path` is relative to `${DATA_DIR:-.data}` so downstream tooling can
  relocate the data directory without rewriting the index.
