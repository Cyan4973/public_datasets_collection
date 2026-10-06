# UVA_VPTS German weather-radar animal reflectivity (eta) float32

This recipe collects the animal reflectivity `eta` (cm^2/km^3) from the
German part of the UVA_VPTS deposit (Zenodo record 14711244, published
2025-01-25, CC0). vol2bird derived these vertical profiles of biological
targets, mostly nocturnally migrating birds, from the C-band volume scans of
18 German Weather Service (DWD) radars. Each profile has 25 altitude bins of
200 m, covering 0 to 4800 m above sea level.

Each published radar-month VPTS file becomes one sample: a row-major
little-endian float32 matrix of shape `(profiles, 25)`, with rows in stored
order (profile, then height).

## Source and pins

| file | bytes | Zenodo MD5 |
| --- | ---: | --- |
| `de.tgz` | 1,231,349,011 | `77459683bb0d30c16af21ab2d706b260` |
| `coverage.csv` | 920,447 | `cdc339b008122fcebc9d3414969c07a4` |
| `vpts-csv-table-schema.json` | 7,238 | `f94e2865bb363c56f37e1b4cd87edba2` |

Record 14711244 is the latest version of concept DOI 10.5281/zenodo.13629330.
`download.sh` validates the record id, the title, the publication date, the
`cc-zero` license and the three file pins from the Zenodo API before it
downloads anything. It then fetches `de.tgz` with resumable, stall-bounded
curl and enforces the exact size and MD5. Finally it streams the archive to
check that its members equal the 465 German radar-months listed in
`coverage.csv`. `discover.sh` prints the same metadata.

The frozen DOI deposit was chosen over the mutable Aloft S3 bucket
(`uva/monthly/de*`, 465 objects, 1,234,570,662 bytes, LastModified
2024-09-02). The archive's 465 members also total exactly 1,234,570,662
bytes. The bucket copy of `deeis_vpts_201603.csv.gz` is byte-identical to the
deposit member (MD5 `773298305073bb36950cfec03733fa53`). The Belgian
(`be.tgz`) and Dutch (`nl.tgz`) archives are not downloaded. The Aloft
`baltrad/` prefix depends on inputs under an OPERA research-only agreement
and is never touched.

## License

The Zenodo record declares `cc-zero`. The Aloft FAQ
(https://aloftdata.eu/faq/) says: "The data in the bucket are available
under a Creative Commons Zero waiver". The deposit lists the bucket's
`uva/monthly/` prefix as `isVariantFormOf`. Please cite the deposit and
Desmet et al. (2025), Scientific Data, doi:10.1038/s41597-025-04641-5.

## Natural record (protocol rule 8)

The deposit documents its file unit as "organized per country (.tgz file),
radar (directory), year (directory) and month (.csv.gz file)". A VPTS
("vertical profile time series") is the dataset's object: bioRad's `vpts`
class and the VPTS CSV format both define the record as a time series of
profiles for one radar. A single profile (25 values per variable) is one
time step of that series, comparable to one timestamp of a sensor series,
not an independent record. Adjacent profiles are strongly correlated in time,
and the series is what radar-aeroecology analyses consume. One sample is
therefore one published radar-month file, and no files are concatenated.

## Realized output

| metric | value |
| --- | --- |
| samples (radar-months) | 465 from 18 radars, 2015-02 to 2019-05 |
| values / bytes | 28,369,050 float32 / 113,476,200 bytes |
| median sample | 71,200 values (min 4,800, max 223,100) |
| profiles | 1,134,762 |
| missing (NaN) | 3,580,450 (12.62%): 3,237,714 `NaN`, 342,736 blank, 0 `NA` |
| zeros | 2,518,712 (10.16% of finite values) |
| bit-exact binary32 recovery | 24,771,271 of 24,788,600 finite values (99.93%) |
| coarse decimals | 17,329 (0.07%), all in 7 fixed-decimal files |
| aggregate SHA-256 of sample SHA-256s | `a763eb29196e357598a8df0ab52676f1089a757e22186349e49f8560eb1f8ada` |

The realized per-month and per-day row counts equal coverage.csv for every
file.

- Per-sample NaN fraction ranges from 0.16% to 38.9%, and the zero fraction
  of finite values from 0.01% to 42.7%. No month is all-NaN, constant or
  all-zero.
- The largest values reach about 21,117 cm^2/km^3, at deemd 2016-02.

## Homogeneity and exclusions

- **One quantity, one chain.** The series is `eta` in a single unit, produced
  by one processing chain: UvA vol2bird on DWD C-band volumes. Every file has
  `rcs` 11 cm^2 and `sd_vvp_threshold` 2 m/s (enforced).
- **One height lattice.** coverage.csv reports `unique_heights` = 25 for
  every German radar-day, and the build enforces the 0..4800 m, 200 m step
  order for every profile.
- **Wavelengths.** All are C-band. Two radars record a metadata change within
  the period: defbg (5.286 and 5.315 cm) and detur (5.344 and 5.35 cm).
- **Radar ids.** The radar column holds the WMO number in 394 files, the ODIM
  code in 68, and both in 3 (2017-10 at deboo, dehnr and deros). Each radar
  maps to exactly one WMO number.
- **Source names.** In 968,180 profiles, `source_file` names vol2bird v0.3.20
  outputs. The other 166,582 profiles carry R temp-file names (e.g. the deemd
  files). The processing parameters are identical.
- **Excluded columns.**
  - `dens` equals eta/11 where a bin is retained and 0 where screening zeroed
    it, so it is a scaled, masked copy of eta. In the probes, eta itself was
    not zeroed by the sd_vvp threshold where dens was.
  - `dbz` is a log transform of eta, and `dbz_all` includes precipitation.
  - Also excluded: the kinematics (`u`, `v`, `w`, `ff`, `dd`, `sd_vvp`), the
    `gap` flag, the `n_*` point counts and the constant radar metadata.
- **Cadence** is a property of the source, not a defect. 461 radar-months
  have 15-minute profiles and 4 (deasb 2019-02 to 2019-05) have 5-minute
  profiles. Missing profile times (radar outages) are not filled. The rows
  are the profiles that exist.
- **Partial months** are kept as published. The smallest are deemd 2017-03
  and deess 2019-04 (2 days, 4,800 values each).
- **Stored order** is kept, so profile times within a file are unique but not
  always sorted. In denhb 2015-04 and deumd 2015-09, one day's hourly
  profiles are listed before that day's 15-minute profiles (one order break
  each, index `datetime_order_breaks`).

## Conversion and missing values

- **Missing values.** The schema's `missingValues` (`''`, `'NA'`, `'NaN'`)
  become the canonical float32 quiet NaN `0x7fc00000` and are counted per
  sample. They mark bins below the antenna (for example, the four lowest bins
  at deeis, whose antenna is at 798 m), bins without a valid biological
  signal, and failed scans.
- **Rounding.** Each finite decimal token is rounded once to IEEE binary32.
- **Three decimal writer styles occur:**
  - 15 significant digits, the R default, e.g. `60.4372711181641`.
  - The shortest repr of the binary32-exact double, e.g. `56.06618118286133`
    in deess 2019-04.
  - Fixed 7–10 decimal places, e.g. `912.9224854` and `96.134643555`. This
    style appears only in deboo 2017-11 and 2018-11, dehnr 2017-11 and
    2018-11, deros 2017-11, defld 2018-11 and deess 2018-11.
- **Faithfulness check.** Every token must lie within one unit of its last
  written decimal place of its nearest binary32. The observed maximum is 0.568
  units, from R's last-digit rounding. Each token is then classified:
  - `exact`: the decimal equals the binary32.
  - `unique`: exactly one binary32 lies within one last-place unit, so the
    source binary32 is recovered bit-exactly.
  - `coarse`: the token was published with fewer digits than binary32
    resolution, so the stored value is the binary32 nearest to it. These are
    small magnitudes in the fixed-decimal files.

  The index records the coarse count per sample. The screener's suggested
  strict test, `float(text) == float32(float(text))`, would have rejected the
  15-digit style, which is most of the deposit.
- **Representation class.** The series is labelled
  `derived_operational_numeric` because the stored value is the published
  decimal rounded once. The width is the source's native binary32.
- **Fatal conditions:**
  - other tokens (including `Inf`), negative values, or tokens off the
    binary32 lattice
  - header or height-lattice defects
  - duplicate or out-of-month datetimes
  - an inconsistent radar id
  - row counts that differ from coverage.csv per month or per day

  Degenerate samples (all-NaN, constant or all-zero) are also rejected. The
  build reports every problem before failing.

## Scripts

```bash
bash staging/aloft_uva_vpts_animal_reflectivity_f32/download.sh   # ~1.23 GB
bash staging/aloft_uva_vpts_animal_reflectivity_f32/build.sh      # ~2.5 min
bash staging/aloft_uva_vpts_animal_reflectivity_f32/verify.sh     # ~2 min
```

- `scripts/vpts.py` contains `inventory`, used by download, and `build`. It
  streams the tgz with `tarfile` (no extraction). It validates and skips the
  545 AppleDouble `._*` entries and the PAX xattr headers of the macOS-made
  archive. It reads the multi-member gzip CSVs with `gzip.decompress`.
- `scripts/verify_vpts.py` is an independent re-derivation: plain line
  splitting with `array('f')` conversion and its own last-place, neighbour
  and coverage logic. It byte-compares every sample and checks the index,
  manifest totals, NaN bit patterns, coarse and order-break counts, sample
  hashes, aggregate hash and non-degeneracy.

Logs are written to `.data/logs/aloft_uva_vpts_animal_reflectivity_f32/`.
Ingest statistics are in
`.data/filtered/aloft_uva_vpts_animal_reflectivity_f32/ingest_stats.json`.
