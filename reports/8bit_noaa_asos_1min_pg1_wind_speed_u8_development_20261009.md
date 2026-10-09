# NOAA ASOS one-minute page-1 wind speed uint8 development

## Outcome

Accepted `noaa_asos_1min_pg1_wind_speed_u8`. It collects two native uint8 series from NOAA NCEI ASOS one-minute page-1 observations (DSI 6405):
- `wind_speed_2min_avg_kt_u8`: the 2-minute average wind speed;
- `wind_speed_5s_peak_kt_u8`: the highest 5-second wind speed in each minute.

Both are whole knots, one value per reported minute, one sample per station-month file.

Station wind speed was previously in the corpus only at coarser cadence and wider types:
- local: GHCN-Daily AWND/WSFG (16-bit, daily) and ISD-lite `isd_wspd` (16-bit, hourly);
- downstream: NDBC `ndbc_wspd`/`ndbc_gst` (64-bit) and `ghcn_awnd` (16-bit).

This recipe adds minute-cadence wind at 8 bits from a product not ingested anywhere. That is new content in a known modality.

## Source and rights

- Source: NCEI `www.ncei.noaa.gov/data/automated-surface-observing-system-one-minute-pg1/access/2024/MM/asos-1min-pg1-<ICAO>-2024MM.dat`.
- Files: 360 station-month files, 30 stations × 12 months of 2024. Exact byte sizes and listing timestamps are pinned in `sources.tsv`; the total is 1,580,854,971 bytes. `discover.sh` regenerates the pins from the directory listings.
- Documentation: `doc/asos-1min-pg1_documentation.pdf` (2022-11-08), SHA-256 `ccd48036c89729f01b77253ae82f46e63aab5012036c04b6a62ee3bd5e8afdab`. It defines "Speed of 2-minute average wind (knots)" and "Speed of Maximum 5-second wind (knots)".
- License: U.S. Government public domain. These are federal works of NWS, FAA, DoD and NCEI (17 U.S.C. 105).
  - The NCEI ISO record `gov.noaa.ncdc:C00386` is saved and text-checked by `download.sh`. It has a single resource-constraint block containing only a "Cite as" request, plus the NOAA/NCEI distribution-liability disclaimer.
  - The record links the exact `/access/` tree.
  - This is the same basis as the accepted `noaa_isd_lite` recipe.

## Shape and conversion

- **Format.** Each natural record is one station-month `.dat` file: fixed-width ASCII, 112 characters plus LF per line, at most 44,640 one-minute rows.
- **Fields read.** The two speed fields come from fixed columns `[74:79]` and `[84:89]` as right-justified ASCII integers and are written unchanged as uint8 in file (time) order.
- **Missing values.** `M` or blank values are dropped for that series only and nothing is imputed. A sample is the sequence of valid reported minutes, not a gap-filled lattice.
- **Not emitted.** Wind directions (0–360, not native u8), visibility extinction coefficients and runway visual range.
- **Structural screening.** A row is dropped for both series and counted if it fails any of these:
  - printable ASCII, the expected WBAN/ICAO prefix, and the file's LST year-month;
  - right-justified wind fields, with `M` only at offset 3 of its field;
  - a visibility region of 0–3 pairs of extinction value and one-letter flag;
  - a tail that is blank, `M`, or one runway group.

  These checks remove:
  - garbled transmissions with shifted columns (KRAP 2024-01, KPHL 2024-12, KPWM 2024-12, single rows at KGLD and KDSM);
  - undocumented bracket-flagged wind groups.
- **Duplicated minutes.** Every row whose LST minute occurs more than once in a file is dropped. Some files interleave two different instruments' readings for the same minute over 12-hour blocks; for example, KGRI 2024-01 alternates 12 kt and 4 kt records.

## Accepted output

| | count |
| --- | --- |
| rows read | 13,989,867 |
| rows with a malformed or bracketed wind field | 7,674 |
| rows with a garbled visibility region | 2,214 |
| rows with a garbled runway tail | 13 |
| rows of a duplicated LST minute | 19,220 |
| rows kept | 13,960,746 |

`wind_speed_2min_avg_kt_u8`:
- 360 samples, 13,834,055 values (126,691 missing).
- Sample sizes: minimum 20,268, median 38,911, maximum 44,016 values.
- Range 0–54 kt. Mode share median 0.101, maximum 0.208.

`wind_speed_5s_peak_kt_u8`:
- 360 samples, 13,863,221 values (97,525 missing).
- Sample sizes: minimum 20,270, median 38,956.5, maximum 44,059 values.
- Range 0–73 kt. Mode share median 0.078, maximum 0.158.

Totals:
- 720 primary samples and 27,697,276 bytes, median 38,928.5 values.
- Aggregate SHA-256 of the samples in index order: `01ed8b2059d5bad4ad48ee235b1151ae37d7dcba6ae2fb550f637fbb068485b1`.

Breadth (zlsim): verdict OK.
- The nearest family for both series is `lora24_rssi_i8`, at distance 0.0635 (average) and 0.0625 (peak). Its compressor matches these samples exactly (loss 0.0), but the feature distance is above the 0.05 redundancy threshold.
- Next nearest are `power_hvac` and `ena_fastq_phred_u8`, both at 0.071.
- Own compression ratio: 4.61x for the average series, 3.07x for the peak series.

## Judge checks

- **Gate.** `python3 tools/autocollect/gate.py staging/noaa_asos_1min_pg1_wind_speed_u8`: PASS with no warnings.
- **Verify.** Ran `verify.sh` myself: `verify ok` (82 s). The independent regex parser matches every sample byte, sha256, index field, ingest count and manifest total. `build.sh` reads only `.data/downloads`, the script has no network imports, and no script contains credentials.
- **Bytes**, inspected with stdlib Python under `/tmp/autocollect/noaa_asos_1min_pg1_wind_speed_u8/`:
  - The global histogram peaks at 4–8 kt.
  - Zero is rare (0.28% average, 0.04% peak), consistent with sonic sensors reporting 1–2 kt rather than calm.
  - Changes between consecutive values are 0 in 58% (average) and 40% (peak) of cases, otherwise mostly ±1.
  - No isolated spikes larger than 12 kt (average) or 25 kt (peak).
  - The average exceeds the peak in 0.023% of aligned kept minutes, almost always by 1 kt. Three lone glitch rows exceed 3 kt (peak 0, direction `M`), which is negligible.
  - 99.97% of consecutive kept minutes are exactly one minute apart; there are 1,948 gaps over an hour, all source outages.
  - No duplicate sample hashes.
- **Dropped rows.** Inspected raw examples of each dropped class: KGRI interleaved duplicate blocks, KABR and KABQ bracket-flagged wind groups (3,305 such rows carry digits), and garbled lines. Dropping them is conservative and costs about 0.2% of rows.
- **Documentation.** Text extracted from the pinned DSI 6405 PDF confirms both fields are speeds in knots.
- **Rights.** Read the saved ISO record's constraint blocks myself.
- **Novelty.** Ran `novelty.py --url/--terms`, `--vocabulary`, `--type/--instrument/--archive` and `--list-width 8`:
  - there is no ASOS one-minute or DSI 6405 source anywhere;
  - there is no 8-bit wind family locally or downstream;
  - `noaa_isd_lite`'s 8-bit series are calendar helpers and its wind is 16-bit.
- **Two series from one file.** The two series are distinct documented source fields with different statistics, matching the precedent of separate GHCN AWND and WSFG recipes. They are not a duplicated view.
- **Volume.** 27.7 MB over 360 natural samples per series. A larger pull would be possible under the 5 GB cap but is not needed. The 1.75% extraction ratio is inherent: there is no leaner first-party minute source.
