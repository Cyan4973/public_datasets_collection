# UK-DALE individual-appliance-monitor real power uint16 development

## Outcome

Accepted `ceda_ukdale_iam_appliance_power_u16`. The recipe collects per-appliance real (active) power from UK-DALE, the UK Domestic Appliance-Level Electricity dataset (2017 edition, UKERC Energy Data Centre, hosted by CEDA). It takes every channel recorded by an EDF EcoManager Transmitter Plug, the individual appliance monitor (IAM), in houses 2-5. Each `house_N/channel_M.dat` record becomes one uint16 little-endian sample of integer watts in time order, at about one reading every 6 s.

This is a new source, and per-appliance plug power is a new quantity for the corpus. The nearest existing electricity families measure different things:

- `household_power_uci`: one house, 1-minute whole-house kW plus three circuit sub-meters in Wh.
- `appliances_energy_uci`: 10-minute house-level Wh.

## Source and rights

- Archive: CEDA `UK-DALE-2017/UK-DALE-FULL-disaggregated/ukdale.zip`
  - 3,585,155,959 B, ZIP64, 196 members
  - ETag `"59425b9c-d5b12377"` (nginx mtime-size: 2017-06-15 10:04:12 and 3,585,155,959 B)
  - Last-Modified `Thu, 15 Jun 2017 10:04:12 GMT`
  - Catalogue md5 `a870331dc3f296ae187133dc3f954df2`
- Fetch: the full archive is never downloaded. The recipe fetches 51 exact member byte ranges totalling 221,188,825 B, plus a 64 KiB tail holding the central directory and the metadata YAML.
- Integrity, per member:
  - HTTP 206 with the exact Content-Range
  - pinned ETag and Last-Modified
  - local header equal to the central directory entry
  - DEFLATE stream ending exactly at the member boundary
  - CRC32 and uncompressed size match
- Licence: CC BY 4.0.
  - The CEDA ReadMe section "Disaggregated (6s) appliance power and aggregated (1s) whole house power" (data location `.../UK-DALE-FULL-disaggregated`) states "Rights Creative Commons Attribution 4.0 International (CC BY 4.0)".
  - The in-archive `metadata/dataset.yaml` `rights_list` says the same.
  - `download.sh` re-checks both on every run.
- Citation: Kelly & Knottenbelt, *Scientific Data* 2:150007 (2015).
- Recovery notice: CEDA posted a recovery notice after an archive deletion on 18 Nov 2025. The file is back on disk with its original 2017 metadata, and all 51 member CRC32 values check.
- Personal data: five anonymised homes with no identifiers. Only watts and auxiliary timestamps are emitted.

## Shape and conversion

- **Natural record.** One complete IAM channel file, one appliance plug's full logged series. Line format: `<unix_seconds> <watts>`.
- **Selection.** Every `elec_meters` entry whose `device_model` is `EcoManagerTxPlug` in `metadata/building{2..5}.yaml`:
  - house 2: channels 2-19
  - house 3: channels 2-5
  - house 4: channels 2-6
  - house 5: channels 2-25

  The selection is re-derived from the archive's own metadata on every download and in verify, and must equal the pinned `members.tsv`.
- **Excluded:**
  - `channel_1`, the whole-house transmitter, which records apparent power in VA
  - `mains.dat`, the 1 s sound-card meter (floats, with voltage)
  - `*_button_press.dat` and `labels.dat`
  - all of house 1: its 48 IAM channels hold about 587 M readings, about 1.17 GB as uint16, which exceeds the 1 GB cap
- **Conversion.** Raw DEFLATE inflate with CRC checks, then a strict full-text match of `([0-9]+ [0-9]+\n)+`. Watts become uint16 LE (primary); unix seconds become uint32 LE (auxiliary, aligned 1:1, because sampling is irregular). A malformed line or an out-of-range value is fatal. Nothing is dropped, clipped or filled.
- **Homogeneity.** One sensor model, active power, integer watts on a 1 W lattice, rated 0-3300 W, one logger, nominal 6 s cadence. Appliances differ, but the unit, scale lattice and generation process are the same. Three house 4 plugs feed more than one appliance (`tv_dvd_digibox_lamp`, `kettle_radio`, `washing_machine_microwave_breadmaker`); each is still one IAM channel.

## Accepted output

| Measure | Value |
|---|---|
| Primary samples (`ukdale_iam_active_power_w_u16`) | 51 |
| Primary values | 82,837,497 |
| Primary bytes | 165,674,994 |
| Readings per sample: median / min / max | 1,842,782 / 10,215 / 2,806,036 |
| Auxiliary bytes (`ukdale_iam_unix_time_s_u32`) | 331,349,988 |
| Watt range | 0-3,998 (650 readings in 13 channels above the 3,300 W rating; none at 3,999-4,000) |
| Zero readings | 38.6% |
| Distinct values (pooled) | 3,436 |
| Order-0 entropy, value-weighted per sample / pooled | 1.50 / 3.98 bits |
| Timestamp steps | 0 non-increasing; 1,237 gaps over 120 s |
| Aggregate primary SHA-256 (index order) | `53daf18f3824a4ae637a328fa2cff43b85d66bea65aa954c99ba211050a7b0eb` |

Sparse natural records are kept and disclosed:

| Channel | Readings | Content |
|---|---|---|
| House 5 PS4 (channel 11) | 10,215 | 10,214 zeros and one 2 W reading, over the meter's metadata timeframe of 17.5 h (0.012% of values) |
| House 5 steam_iron | 985,779 | 99.95% zeros |
| House 5 electric_hob | 1,842,782 | 99.4% zeros |
| House 5 vacuum_cleaner | 79,850 | 98.5% zeros |

## Judge checks

- **Gate.** `python3 tools/autocollect/gate.py staging/ceda_ukdale_iam_appliance_power_u16` passed with no warnings.
- **Verify.** I ran `bash staging/ceda_ukdale_iam_appliance_power_u16/verify.sh`; it printed `verify=ok` with the totals above. `verify.py` does not import the build code. It re-derives the selection, re-inflates, parses with a separate partition parser, re-encodes with `struct` and byte-compares all 102 samples. `build.sh` reads only local files and first requires `selection.tsv` to equal `members.tsv`.
- **Bytes.**
  - Read all 51 primary samples. Their SHA-256 values are distinct.
  - Per-appliance modes are plausible: router 6 W, monitor 60 W, fridge 10-11 W idle and 86-110 W running, gas boiler 8/106 W, kettle events about 2.95 kW for about 2 min.
  - Timestamps start Feb 2013 (house 2) and Jun 2014 (house 5); steps are mostly 6-7 s.
  - I decoded house 5 channels 25 and 11, house 3 channel 3 and house 2 channel 8 with my own zlib and text code. Watts and timestamps match the samples exactly.
- **Scope.** The `device_model` counts in `building2-5.yaml` are EcoManagerTxPlug 18/4/5/24. The selection is exactly those 51 meters.
- **Rights.** Read the downloaded ReadMe section and `dataset.yaml`; both state CC BY 4.0 for this object.
  - The catalogue listing was still 503 on my probe. The screener transcript from earlier on 2026-10-06 shows it matching size and md5.
  - The ETag decodes to the pinned mtime and size.
  - No credentials appear in any script.
- **Novelty.** `novelty.py` with the ukdale.zip URLs (both hosts) and the terms ukdale, UK-DALE, EcoManager, NILM, disaggregat, smart plug, submeter, REFIT and REDD found only the candidate itself. Broader electricity terms surface only the UCI whole-house and house-level families.
- **Judgment call.** I kept the near-constant house 5 PS4 channel. Its zeros are genuine 0 W readings over the publisher's own short meter timeframe, not zero fill. Precedent keeps native zeros (EIT thorax) and excludes only filled or duplicate records (GridGnosis PMU hour, UCI hydraulic). It is 20 KB of 165.7 MB.
