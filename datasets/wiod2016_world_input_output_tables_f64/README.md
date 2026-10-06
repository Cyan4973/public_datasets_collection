# WIOD 2016 release World Input-Output Tables, current prices, float64

This recipe collects the World Input-Output Tables (WIOTs) of the World
Input-Output Database 2016 release. The release covers 43 countries plus a
modelled Rest of World, with 56 ISIC Rev. 4 industries each, for the years
2000-2014. Each annual table is one natural record and becomes one sample: a
row-major little-endian float64 matrix of flows in millions of US dollars at
current prices.

- Rows (2464): supplying country-industries in source order, AUS, AUT, ...,
  USA, ROW, by industry 1..56 (A01 ... U).
- Columns (2684): 2464 intermediate-use columns (`vAUS1` .. `vROW56`), then
  220 final-demand columns (`vAUS57` .. `vROW61`). The final-demand columns
  are household consumption, NPISH consumption, government consumption, gross
  fixed capital formation, and changes in inventories and valuables, for each
  destination country.

The cells are RAS-balanced full-precision doubles, for example
`5876.83318062628` and `-0.00022121972870081663`. There are many exact zeros
and many tiny values. Negative cells occur only in the final-demand columns
(inventory changes, and a few gross fixed capital formation cells). This
sparse multi-scale structure is the material itself, not a degeneracy.

## Source and license

- Dataset: WIOD, *World Input-Output Database 2016 Release, 2000-2014*,
  DataverseNL, doi:10.34894/PJ2M1C, dataset version 2.1. Distribution date
  2016-11-30.
- File: `WIOTS_in_STATA.zip`, datafile 199103, 638,963,496 bytes, SHA-1
  `cde6085d4233fec2356877aedf21d950de912b78`. It contains 15 DEFLATE members,
  `WIOT2000_October16_ROW.dta` .. `WIOT2014_October16_ROW.dta`, each
  55,216,235 bytes uncompressed. Their CRC-32 values are pinned in
  `scripts/wiod_wiot.py`.
- License: CC BY 4.0. The DataverseNL termsOfUse reads "The World
  Input-Output Database (WIOD) is licensed under a Creative Commons
  Attribution 4.0 International-license." The GGDC release page
  (<https://www.rug.nl/ggdc/valuechain/wiod/wiod-2016-release>) says the same.
  `download.sh` re-checks the termsOfUse on every run.
- Required citation: Timmer, M. P., Dietzenbacher, E., Los, B., Stehrer, R.
  and de Vries, G. J. (2015). An Illustrated User Guide to the World
  Input-Output Database: the Case of Global Automotive Production. *Review of
  International Economics* 23: 575-605. doi:10.1111/roie.12178.

## Why 15 samples

The current-price WIOTs of this release are exactly 15 tables, one per year
from 2000 to 2014. The recipe takes the whole population. Each table is a very
large natural record of 6,613,376 values (52.9 MB), so 15 samples hold 99.2
million values in 793,605,120 bytes. The table is the natural boundary: rows
and columns are coupled by accounting identities (row sums equal total use,
column sums equal intermediate inputs). Splitting a table into country blocks
or rows would be tiling, so the recipe does not do it.

The recipe does not add other material to raise the count, because the other
WIOD tables are different regimes:

- the previous-year-price WIOTs (different price basis, Excel only)
- the national input-output tables
- the supply and use tables (different shapes and semantics)
- the 2013 release (1995-2011, 41 regions x 35 ISIC Rev. 3 industries, a
  different classification and shape)

## Conversion

The Stata members use release 118 with LSF (little-endian) byte order. Each
row is 21,640 bytes: 160 bytes of label fields (`IndustryCode` str7,
`IndustryDescription` str147, `Country` str3, `RNr` byte, `Year` int), then
2685 doubles (2684 use columns plus `TOT`).

For each year, `build.sh` does the following:

1. Streams the member with `zipfile`. Nothing is extracted to disk.
2. Parses the header and the 14-entry `<map>`, and checks every section
   boundary against the map. It checks K=2690, N=2472, the exact variable
   names and type codes, and the row width computed from the types.
3. Jumps to the `<data>` offset.
4. For each of the first 2464 rows, checks the row label: country, industry
   number, year, and an industry-code sequence identical for every country
   and year.
5. Copies the 2684 retained doubles byte-for-byte to the sample.

Because the cells are copied as bytes, sign, `-0.0` and every bit pattern are
preserved. The TOT column (the row sum) is dropped. The eight summary rows are
dropped: `II_fob` (column sum), `TXSP`, `EXP_adj`, `PURR`, `PURNR`, `VA`,
`IntTTM`, `GO`. Taxes, adjustments, value added, margins and gross output are
different quantities from inter-industry deliveries. The row and column labels
are written to `filtered/<id>/table_axes.json` for reference. They are not
emitted as a series.

Missing-value policy, shared by build and verify, is fatal on any of:

- Stata missing doubles (>= 2^1023)
- NaN or infinity anywhere in a row
- magnitudes above 1e9 million US$
- a label or layout change

`verify.sh` decodes each member again by a separate path. It walks the Stata
tags sequentially and cross-checks them against `<map>`. It unpacks and
repacks every row with `struct` and compares bit-for-bit with the sample. It
checks three accounting identities against the dropped source fields:

- Row sums equal TOT, to `1e-9 * sum|row| + 1e-6`. The observed maximum
  relative deviation is 4e-11.
- Column sums equal the II_fob row, to `1e-6 * sum|column| + 1e-6`. The
  observed maximum is 2.2e-7 of the column's absolute sum. The published
  II_fob was stored at a slightly different rounding stage, so this identity
  is not exact. A shifted column would be off by O(1).
- The GO row equals TOT for every country-industry, so gross output of
  using industry j equals total use of supplying row j. This holds exactly in
  all 15 years and cross-checks row and column alignment.

It also checks the index statistics and SHA-256 values,
rejects constant or mostly-zero matrices, requires exactly 15 distinct
samples, and checks that the manifest totals match the output.

## Realized output

The 15 samples hold 99,200,640 float64 values in 793,605,120 bytes, each of
shape [2464, 2684]. The aggregate SHA-256 over the per-sample SHA-256s, in
year order, is
`3f817495fbdba5b932e33b905fed3e7aa258cb2a0d211119c04d29e39fb37ed6`.

| | 2000 | 2014 |
|---|---|---|
| min (million US$) | -66,577.3 | -70,026.9 |
| max (million US$) | 1,443,258.2 | 2,775,513.5 |
| zero cells | 18.1% | 17.5% |
| negative cells | 1,767 | 2,109 |
| `-0.0` cells | 0 | 0 |

Other properties of the realized output:

- No Stata missing values or non-finite values occur.
- Structural zeros are part of the WIOD layout:
  - 135-136 supplying rows per year are all zero. These are country
    industries that the national accounts do not report separately: U
    (extraterritorial organisations) for 42 countries, T (households as
    employers) for 11, and some C33, M71-M75, K66, J58-J60, H53 and E37-E39
    rows.
  - 174-177 columns per year are all zero, 174 of them in every year. These
    are the same absent industries as users, plus NPISH final consumption
    for 8 countries.
- In the two years profiled, 39% (2000) and 27% (2014) of cells are positive
  but below 1e-3 million US$ (under $1,000). These are small flows spread by
  WIOD's proportional allocation of bilateral trade. They are real published
  values and are not filtered.
- Per-year statistics, and the lists of all-zero columns, are in
  `.data/filtered/<id>/ingest_stats.json`.

## Running

From the repository root:

```bash
bash staging/wiod2016_world_input_output_tables_f64/download.sh
bash staging/wiod2016_world_input_output_tables_f64/build.sh
bash staging/wiod2016_world_input_output_tables_f64/verify.sh
```

`download.sh` writes about 639 MB to
`.data/downloads/wiod2016_world_input_output_tables_f64/`. Each attempt
re-requests the DataverseNL access URL, which issues a fresh signed
objectstore URL, and resumes with a byte range. `build.sh` writes 15 samples,
793,605,120 bytes in total, under
`.data/samples/wiod2016_world_input_output_tables_f64/wiot_current_price_flows_f64/`.
Logs go to `.data/logs/wiod2016_world_input_output_tables_f64/`.
`python3 scripts/wiod_wiot.py selftest` runs the parser on a synthetic
Stata-118 archive and checks that bad inputs are rejected.

## Novelty

The corpus has no input-output or national-accounts matrix material. The
novelty check found no matching URL, term, registry, ledger or downstream
entry for WIOD or input-output tables. The economics material already at
64 bits is SEC, Census and EIA tables and indicator series, not
inter-industry flow matrices.
