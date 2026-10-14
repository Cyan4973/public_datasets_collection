# SLF WFJ_DailySMP SnowMicroPen S36M force profiles (int16)

Raw penetration-force ADC counts from the SLF SnowMicroPen (SMP), a motorised
micro-penetrometer that drives a 5 mm piezo force tip through the snowpack at
20 mm/s and samples force every 0.00413 mm (~240 samples per mm). Source:
EnviDat package `wfj_dailysmp`, "WFJ_DailySMP - High-Resolution Snow
Stratigraphy at Weissfluhjoch -- Davos 2015-ongoing", DOI
[10.16904/envidat.641](https://doi.org/10.16904/envidat.641).

One sample = one complete `.PNT` penetration profile (natural record), stored
as little-endian int16 counts in source order.

## Scope

- Device S36M only (SMP serial 36, v4 electronics, firmware 406/408), one site
  (Weissfluhjoch study plot), one protocol (DailySMP).
- `raw_data.csv` rows with `File` starting `S36M`, `BestOfDay=1` (478) and
  `Quality=1` ("good"; the provider recommends Quality 1 where possible): 438.
- Of those, only profiles recorded with sensor and amplifier range 5000 pC:
  **291 profiles**, 2015-11-30 .. 2020-12-21, 119,708,056 values,
  239,416,112 bytes. Median profile has 478,499 samples (~2 m of travel).
- Excluded: the 147 Quality=1 profiles (2019-03-27 .. 2020-12-16) recorded at
  range 10000 pC. Their conversion factor is 0.0026 N/count instead of
  ~0.0013, so the same force reads as half as many counts. They are a
  different scale and listed in `excluded_gain10000.tsv`.
- Within the kept set, five force sensors were used (sensitivity
  116-118 pC/N), so the header conversion factor varies by ±0.9% only
  (0.0012932, 0.0013042, 0.0013155 N/count). The factor is recorded per
  sample in the index and not applied.

## Decode

The 3.13 GB `raw_data.zip` is never downloaded whole. `download.sh` reads its
central directory with a range request, checks it against the pinned member
table `members.tsv` (offset, sizes, CRC32, exact case-sensitive name; names mix
`.PNT` and `.pnt`), then range-fetches each member's local header plus deflate
data. It takes the data offset from the local header's own name/extra lengths
(28-byte local extra field), raw-inflates the data and requires the exact size
and CRC32.

The PNT layout was checked on real S36M files against snowmicropyn's
`Pnt.load` (github.com/slf-dot-ch/snowmicropyn, `snowmicropyn/pnt.py`):

- 512-byte big-endian header; `samples.force.count` = `>l` at offset 358;
  force samples = that many `>h` from byte 512; anything after is padding
  (`0x7fff`, `0xffff` or ASCII fill observed) and is ignored.
- The card's probe described an SMP5 (S36N, 2024) file with 1024-byte header
  and a count at offset 2. That does **not** apply to S36M: the offset-2
  field is always larger than `samples.force.count` here, and data begin at 512.
- force [N] = count x `samples.conv.force` (`>f` at offset 10), as in
  snowmicropyn's `Profile`.

Kept as native content: the ~10 cm air segment above the surface (low counts
~10-30), the full snowpack, and sensor-overload saturation (32767) at the
bottom of some profiles. The first word at byte 512 is often an outlier
(e.g. 8202, 7061; 185 of the 291 kept profiles). It is kept,
matching snowmicropyn, which returns it as sample 0.

## Files

- `members.tsv`: the 291 pinned zip members with header-derived count, factor,
  range and sensor serial.
- `excluded_gain10000.tsv`: the 147 Quality=1 profiles dropped for gain.
- `discover.sh` + `scripts/discover_select.py`: reproduce both TSVs from the
  CSV, central directory and 4 KB member prefixes (writes under
  `$DATA_DIR/discovery/`). Not part of the download/build path.
- `scripts/zip_members.py`: central-directory check, member inflate + CRC.
- `scripts/build_smp.py`: header assertions and int16 emission.
- `scripts/verify_smp.py`: independent re-selection and struct re-decode.

## License

EnviDat lists the package as CC BY-SA (`license_id: cc-by-sa`,
https://creativecommons.org/licenses/by-sa/4.0/). The data folder also holds an
MIT `LICENSE` ("Copyright (c) 2025 WSL Institute for Snow and Avalanche
Research SLF"), which `download.sh` fetches and checks. Cite: Löwe, H., Proksch,
M., et al. (2025), EnviDat, doi:10.16904/envidat.641.

## Run

```bash
bash staging/slf_envidat_wfj_snowmicropen_force_i16/download.sh   # ~152 MB over the wire, ~243 MB on disk
bash staging/slf_envidat_wfj_snowmicropen_force_i16/build.sh
bash staging/slf_envidat_wfj_snowmicropen_force_i16/verify.sh
```
