# AfSIS Phase I soil mid-infrared absorbance spectra (float32)

This recipe collects the mid-infrared (MIR) diffuse-reflectance absorbance
spectra of the Africa Soil Information Service Phase I (AfSIS1, 2009-2013).
The spectra were published by World Agroforestry (ICRAF) as Dataverse dataset
[doi:10.34725/DVN/QXCWP1](https://doi.org/10.34725/DVN/QXCWP1), version 1.1,
released 2025-06-19.

Soil was sampled with the Land Degradation Surveillance Framework (LDSF) at
two depths (0-20 cm topsoil, 20-50 cm subsoil). Sites were randomized across
19 sub-Saharan African countries. Per the dataset description, all ~18,500 MIR
measurements were centralized at ICRAF's Soil-Plant Spectral Diagnostics
Laboratory in Nairobi on a Bruker Tensor 27 with HTS-XT. The deposit holds one
CSV per country.

## What is emitted

One sample per soil-sample spectrum, which is the natural record. Each sample
is the row's 1,749 absorbance values as raw little-endian float32 (6,996
bytes). Values are in source column order: descending wavenumber from
4001.6 to 601.7 cm-1, at about 1.93 cm-1 spacing. The provider removed the
atmospheric CO2 band, so the grid jumps from m2381.7 to m2350.8. All 19 files
share the same byte-identical 1,753-column header (SHA-256
`570c81aa54a569adea4c11b444c4861758296f283e06f77c95c3e0023b830d11`), checked
before use. The bookkeeping columns `Num`, `SSN`, `Depth` and `Country` are
not emitted. They appear in the sample index as provenance (`ssn`, `depth`,
`country_column_value`, `source_datafile_id`, `source_row`, `source_num`).

Samples go to
`.data/samples/icraf_afsis1_soil_mir_spectra_f32/afsis1_soil_mir_absorbance_f32/<SSN>.bin`.
The index is at `.data/index/icraf_afsis1_soil_mir_spectra_f32/samples.jsonl`.
Ingest statistics, including the full wavenumber label list, are in
`.data/filtered/icraf_afsis1_soil_mir_spectra_f32/ingest_stats.json`.

The per-country CSVs are only distribution bundles, so spectra are never
concatenated per country. Topsoil and subsoil are the same measurement under
the same protocol, not different regimes.

## Why float32 (and not float64)

The CSV prints decimals with up to 8 fractional digits. Every cell of every
emitted spectrum sits on a 2.5e-7 lattice. Of the 15,954,604 cells printed
with 8 digits, all end in 25 or 75, consistent with means of 4 replicate
6-decimal readings. A binary32 value does not
reproduce the printed digits. It does preserve the information exactly while
|absorbance| < 4:

- the lattice integer q = value / 2.5e-7 satisfies |q| < 16,000,000 < 2^24;
- below 4, the binary32 half-ulp (at most 2^-23, about 1.19e-7) is smaller
  than half a lattice step (1.25e-7), so `round(f32 * 4e6) == q`.

`build.sh` and `verify.sh` assert this for every cell, using an exact integer
parse and an independent `decimal.Decimal` parse respectively. Any cell that
is off the lattice or has |value| >= 4 is fatal. The self-test checks the
argument on 2.1 million lattice values, including all values just below 4. It
also shows that about 48% of lattice values just above 4 would be lost. Bruker
OPUS stores spectra natively as float32, so float64 would only widen the data.

On the realized output, the maximum |absorbance| is 3.047. The worst float32
error is 0.47681 lattice steps, just below the theoretical ceiling for [2, 4)
of 2^-23 / 2.5e-7 = 0.47684. All 31,914,003 cells recover their lattice
integer. The margin is thin, but it is guaranteed by the bound, not luck.

## Validation and policy

- `download.sh` fetches the pinned version-1.1 listing and validates it: the
  persistent id, the release state, the CC-BY-4.0 terms text, and the id,
  name, original size and MD5 of all 19 files. It then fetches each
  `format=original` CSV by datafile id (10916-10934; the disclaimer PDF 10842
  is skipped). The host is flaky (503/502 bursts and zero-byte stalls) and
  the access API ignores Range. Each file is therefore fetched whole into a
  `.part` file, with curl retries, stall detection and an outer retry loop.
  Before rename, the file must match the Dataverse original size and MD5 and
  the pinned header grid.
- Excluded rows (10 of 18,257) are listed in `ingest_stats.json`. Each class
  is re-derived by rule in build and verify, and must equal a pinned SSN set,
  so any new row of either kind fails the build:
  - 7 placeholder rows whose 1,749 cells are all the literal `NA`, meaning no
    spectrum was recorded: Botswana icr075150 and icr075279, Mali icr015372
    and icr069796, Tanzania icr024965, Zambia icr075956, and Zimbabwe
    icr075550.
  - 3 rows whose every cell is k/3e6 printed to 9 decimals: Kenya icr033584,
    Mali icr037556, and Zambia icr075955. These are 3-replicate means on a
    different tick lattice from every other spectrum, so they stay out of the
    family to keep one lattice. Zambia icr075955 sits directly above the
    all-NA row icr075956.
- Everything else is fatal: partial NA, empty, NaN, exponent-form or
  non-decimal cells, other off-lattice values, wrong column counts, duplicate
  SSNs, Depth values other than Topsoil/Subsoil, unexpected Country values,
  and spectra with fewer than 100 distinct values.
- A spectrum whose float32 bytes duplicate an earlier spectrum would be
  dropped, keeping the first in datafile/row order. None occur in v1.1.
- `verify.sh` re-derives every sample through a separate parse path and checks
  the bytes, lattice recovery of every stored value, all index fields
  (min/max from the stored float32), the ingest statistics, the absence of
  stray files, and the manifest's sample count and byte total.

## Scope

Realized output: 18,247 spectra (9,466 topsoil, 8,781 subsoil) from 18,257
source rows across 19 countries. That is 31,914,003 float32 values in
127,656,012 bytes, 6,996 bytes per sample. The aggregate payload SHA-256 is
`3481c4a2e37c05c59a4f6593574c3662b6a40782dd60b138d6a7d7e1d6aad2ab`. The
dataset description says "~18,500 samples"; the deposit itself has 18,257
rows. Per-country counts run from 304 (Burkina Faso) to 2,080 (Tanzania). The
download is 327,146,877 bytes.

## Run

```bash
bash staging/icraf_afsis1_soil_mir_spectra_f32/download.sh
bash staging/icraf_afsis1_soil_mir_spectra_f32/build.sh
bash staging/icraf_afsis1_soil_mir_spectra_f32/verify.sh
python3 staging/icraf_afsis1_soil_mir_spectra_f32/scripts/afsis_mir.py selftest
```

`discover.sh` documents how `sources.tsv` was derived. It refetches only the
small version listing and diffs the regenerated table against the committed
one.

## License

CC BY 4.0, per the dataset's Dataverse terms of use. Cite: Vågen, T.-G.;
Winowiecki, L. A.; Desta, L.; Tondoh, E. J.; Weullow, E.; Shepherd, K.;
Sila, A. *Mid-Infrared Spectra (MIRS) from ICRAF Soil and Plant Spectroscopy
Laboratory: Africa Soil Information Service (AfSIS) Phase I 2009-2013*. World
Agroforestry (ICRAF) Dataverse, V1.1. https://doi.org/10.34725/DVN/QXCWP1
