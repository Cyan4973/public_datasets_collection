# UK-DALE 2017 individual appliance monitor real power, uint16 watts

This recipe collects per-appliance real (active) power from the UK Domestic
Appliance-Level Electricity dataset (UK-DALE, 2017 edition, UKERC Energy Data
Centre, hosted by CEDA). It takes every channel recorded by an EDF EcoManager
Transmitter Plug, the individual appliance monitor (IAM) placed between one
socket and one appliance, in houses 2-5. Each `house_N/channel_M.dat` record
becomes one uint16 little-endian sample of integer watts in time order. The
readings come about every 6 s.

- Primary series: `ukdale_iam_active_power_w_u16`, 51 samples.
- Auxiliary series: `ukdale_iam_unix_time_s_u32`, the aligned unix-second
  timestamps (uint32), kept because sampling is irregular. It does not count
  toward acceptance.

## Source and licence

- Archive: `UK-DALE-FULL-disaggregated/ukdale.zip` (3,585,155,959 B, ZIP64,
  196 members), ETag `"59425b9c-d5b12377"`, Last-Modified
  `Thu, 15 Jun 2017 10:04:12 GMT`, catalogue md5
  `a870331dc3f296ae187133dc3f954df2`.
- Licence: CC BY 4.0. The CEDA ReadMe entry for "Disaggregated (6s) appliance
  power and aggregated (1s) whole house power" gives `Rights: Creative Commons
  Attribution 4.0 International (CC BY 4.0)`. The in-archive
  `metadata/dataset.yaml` `rights_list` says the same. `download.sh` re-checks
  both.
- Citation: Kelly & Knottenbelt, *Scientific Data* 2:150007 (2015),
  doi:10.1038/sdata.2015.7.
- CEDA posts a recovery notice about a Nov 2025 deletion restored from tape.
  The archive is on disk with its original 2017 Last-Modified, size and member
  CRC32 values; every range response and member is checked against them.

## Scope

All IAM channels of houses 2-5 are included: every `elec_meters` entry whose
`device_model` is `EcoManagerTxPlug` in `metadata/building{2..5}.yaml`.

| House | IAM channels | Span |
|---|---|---|
| 2 | 2-19 (18) | Feb-Oct 2013 |
| 3 | 2-5 (4) | Feb-Apr 2013 |
| 4 | 2-6 (5) | Mar-Oct 2013 |
| 5 | 2-25 (24) | Jun-Nov 2014 |

The DEFLATE members total 1,104,489,538 text bytes. Fetched as exact ZIP
ranges, they are 221,188,825 B.

## Realized output

| Measure | Value |
|---|---|
| Primary samples | 51 |
| Readings | 82,837,497 |
| Primary bytes (uint16) | 165,674,994 |
| Auxiliary bytes (uint32 timestamps) | 331,349,988 |
| Readings per sample: median / min / max | 1,842,782 / 10,215 / 2,806,036 |

Value statistics:

- Watts range from 0 to 3998 across the series.
- 650 readings in 13 channels exceed the 3300 W device rating. Kettles,
  hobs, dish washers and heaters account for most of them.
- No reading is 3999 or 4000 W. So there is no pile-up at the metadata's
  NILMTK clip of 4000 W, and nothing suggests the `.dat` files were clipped.
- 38.6% of all readings are 0 W.
- Timestamps are strictly increasing in every channel. There are 1,237 gaps
  longer than the 120 s maximum sample period.

Sparse channels, kept because they are natural records:

| Channel | Readings | Content |
|---|---|---|
| House 5 `PS4` (11) | 10,215 | 10,214 zeros and one 2 W reading over ~17.5 h. Not constant, so verify keeps it, but nearly so. It is 0.012% of the readings. |
| House 5 `steam_iron` (12) | 985,779 | 99.95% zeros |
| House 5 `electric_hob` (21) | 1,842,782 | 99.4% zeros |
| House 5 `vacuum_cleaner` (25) | 79,850 | 98.5% zeros |

Excluded:

- `channel_1`: the EcoManagerWholeHouseTx site meter, which records apparent
  power in VA.
- `mains.dat`: SoundCardPowerMeter, 1 s float readings with voltage.
- `*_button_press.dat`: switching events.
- `labels.dat`.
- House 1: its 48 IAM channels hold about 587 million readings, about 1.17 GB
  as uint16 on their own (1.63 GB compressed). That would break the 1 GB
  primary cap, and any subset of them would be an arbitrary cut.

Homogeneity: every sample comes from the same sensor model (EcoManagerTxPlug),
reporting active power at 1 W resolution, rated 0-3300 W, through the same
logger (`rfm_ecomanager_logger`) at the same nominal 6 s period. The
appliances differ: kettle, fridge, PCs, washing machine, TV and others.

Notes on the material:

- Some plugs feed more than one appliance. House 4 has
  `tv_dvd_digibox_lamp`, `kettle_radio` and
  `washing_machine_microwave_breadmaker`. Each is still one IAM channel and is
  kept as such.
- Many channels are mostly zero or standby, with intermittent bursts.
- Two channels are short: house 5 `PS4` (channel 11, 10,215 readings) and
  `vacuum_cleaner` (channel 25, 79,850). See the realized-output tables above.
- The metadata records `preprocessing_applied: clip: {upper_limit: 4000}`.
  The emitted values are the `.dat` integers unchanged. The highest reading is
  3998 W, with none at 3999 or 4000.

## Decode path

1. `download.sh`:
   - Checks the licence page and, when reachable, the catalogue listing.
   - Fetches the last 64 KiB of `ukdale.zip`, which holds the ZIP64 end
     records, the central directory and the metadata YAML members.
   - Re-derives the IAM selection from that metadata. It must equal the
     pinned `members.tsv`.
   - Range-fetches each member (local header plus DEFLATE data, ending at the
     next member). Each range must come back HTTP 206 with the exact
     Content-Range, the pinned ETag/Last-Modified, and a local header that
     matches the central directory. The DEFLATE stream must end at the range
     end, CRC32 and uncompressed size must match, and the text must contain
     only digits, spaces and newlines.
   - Validated members are kept, so re-runs resume at member granularity.
   - Files come from `dap.ceda.ac.uk`. `data.ceda.ac.uk` only 302-redirects
     there, and its front end sometimes answers 503.
2. `build.sh` (`scripts/ukdale_iam_build.py`, local only):
   - Inflates each member again and requires the whole text to match
     `([0-9]+ [0-9]+\n)+`.
   - Writes watts as uint16 LE and timestamps as uint32 LE.
   - Any watt value above 65535 or timestamp at or above 2^32 is fatal.
   - Writes `index/<id>/samples.jsonl`, with per-sample min/max, SHA-256,
     house, channel, appliance and source member. Per-channel statistics go
     to `filtered/<id>/ingest_stats.json`: zero fraction, readings above
     3300 W, gaps over 120 s, timestamp monotonicity.
3. `verify.sh` (`scripts/ukdale_iam_verify.py`, independent of the build
   code):
   - Re-derives the selection from metadata, re-inflates every member, and
     parses each line with a separate partition parser under the same strict
     policy.
   - Re-encodes with `struct` and byte-compares every sample.
   - Checks index fields, manifest counts/sizes, the floors and the 1 GB cap.
   - Rejects constant samples.

`discover.sh` shows how `members.tsv` was produced, from one tail range.

```bash
bash staging/ceda_ukdale_iam_appliance_power_u16/download.sh
bash staging/ceda_ukdale_iam_appliance_power_u16/build.sh
bash staging/ceda_ukdale_iam_appliance_power_u16/verify.sh
```
