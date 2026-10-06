# WIOD 2016 world input-output tables float64 development

## Outcome

Accepted `wiod2016_world_input_output_tables_f64`. It collects all 15 annual current-price World Input-Output Tables (WIOTs) of the World Input-Output Database 2016 release, covering 2000–2014. The release has 43 countries plus a modelled Rest of World, with 56 ISIC Rev. 4 industries each.

This is the corpus's first multi-regional input-output material, so it is labelled `new_modality`. The nearest local material is the generic NIST Matrix Market sparse collection. Its Harwell-Boeing `econaus` group contains a few ORANI CGE-model Jacobians in coordinate form; those are not published inter-country flow tables. The other 64-bit economics recipes are SEC, Census and EIA scalar tables.

## Source and rights

- Source: WIOD, *World Input-Output Database 2016 Release, 2000-2014*, DataverseNL, doi:10.34894/PJ2M1C, dataset version 2.1 (released 2025-10-09; distribution date 2016-11-30).
- File: `WIOTS_in_STATA.zip`, datafile 199103.
  - Size: 638,963,496 B
  - Dataverse SHA-1: `cde6085d4233fec2356877aedf21d950de912b78` (enforced)
  - SHA-256: `00563a9e996887454643513b8d68f2a50c1ddf4fa9c219c47dcf5ef54e006fc1`
- Members: 15 DEFLATE members `WIOT{2000..2014}_October16_ROW.dta`, each 55,216,235 B, with CRC-32 values pinned.
- License: CC BY 4.0.
  - The Dataverse termsOfUse reads: "The World Input-Output Database (WIOD) is licensed under a Creative Commons Attribution 4.0 International-license." It links to the CC BY 4.0 deed.
  - There are no termsOfAccess, and the file has `restricted=false`.
  - The GGDC release page says "The WIOD 2016 release is licensed under a Creative Commons Attribution 4.0 International License" and links datafile 199103 as the Stata WIOTs.
  - `download.sh` re-checks the termsOfUse on every run.
- Citation: Timmer et al. (2015), *Review of International Economics* 23:575–605, doi:10.1111/roie.12178.

## Shape and conversion

Each yearly Stata release-118 member (LSF byte order, K=2690, N=2472) is one natural record and becomes one sample.

Each source row is 21,640 B: 160 B of label fields, then 2685 doubles.

What is kept:
- the first 2464 rows: 44 countries × 56 industries, in source order;
- the first 2684 doubles of each row: 2464 intermediate-use columns `vAUS1..vROW56`, then 220 final-demand columns `vAUS57..vROW61`.

The kept doubles are copied byte-for-byte, so the conversion is a pure slice of native IEEE-754 doubles.

What is dropped:
- the label columns (written to `filtered/.../table_axes.json`);
- the `TOT` row-sum column;
- the 8 summary rows `II_fob`, `TXSP`, `EXP_adj`, `PURR`, `PURNR`, `VA`, `IntTTM`, `GO`. These are column totals, taxes, adjustments, value added, margins and output, which are derived or different quantities.

What is not mixed in: the previous-year-price tables, the national IO tables, the SUTs, and the 2013 release.

Missing-value policy, fatal in both build and verify:
- Stata missing values (≥2^1023);
- NaN or infinity;
- magnitudes above 1e9;
- any label or layout drift.

None occur.

The verify path is independent of the build path:
- It walks the Stata tags sequentially and cross-checks them against `<map>`.
- It unpacks and repacks every row with `struct` and compares bit-for-bit with the samples.
- It checks three accounting identities. Row sums equal TOT (worst 3.8e-11 relative). Column sums equal II_fob (worst 2.2e-7 of the column's absolute sum). GO equals TOT exactly in all 15 years.

## Accepted output

- Primary series: `wiot_current_price_flows_f64` (float64, little-endian, native_numeric)
- Samples: 15, one per year from 2000 to 2014
- Shape per sample: [2464, 2684], 6,613,376 values, 52,907,008 B
- Primary values: 99,200,640
- Primary bytes: 793,605,120
- Median sample: 6,613,376 values
- Value range: −76,302.9 (2008) to 2,775,513.5 (2014) million US$
- Zero fraction: 17.5–18.2% per year
  - 135–136 all-zero supplying rows per year
  - 174–177 all-zero columns per year
- Negative cells: 1,767–2,528 per year, only in the GFCF and inventory final-demand columns
- `-0.0` cells: 0
- Aggregate SHA-256 over the per-sample SHA-256s: `3f817495fbdba5b932e33b905fed3e7aa258cb2a0d211119c04d29e39fb37ed6`

The recipe takes the whole current-price population, so 15 samples is the source limit. Each sample is a 52.9 MB natural record, and splitting tables would be tiling.

## Judge checks

- **Gate.** `python3 tools/autocollect/gate.py staging/wiod2016_world_input_output_tables_f64` passed with no warnings.
- **verify.sh.** I ran it myself: exit 0. All 15 years were OK bit-for-bit and `verify_summary samples=15 bytes=793605120` was printed.
- **Selftest.** `wiod_wiot.py selftest`, run in a scratch directory, passed and rejected all four injected faults.
- **build.sh.** It reads only the local archive under `.data/downloads/` and makes no network calls.
- **Independent decode.** My own minimal decoder (locate `<data>`, 21,640 B rows, offset 160) matched rows 0, 1234 and 2463 of the 2003 and 2011 samples byte-for-byte. Rows 2464 and 2471 are `II_fob` and `GO`, which are correctly excluded.
- **Byte statistics** (2000, 2007, 2014):
  - About 93% of nonzero values have fewer than 4 trailing mantissa zero bits, so the 64-bit width is honest.
  - Magnitudes peak at 1e-3..1e-1 million US$. A RAS tail goes down to about 1e-37 in 2000.
  - Negatives occur only in final-demand suffixes 60 and 61.
  - The README's tiny-value shares (39% and 27% below 1e-3) are reproduced.
- **Redundancy.** Between consecutive years, 0–1 nonzero cells are identical out of about 5.4M. 2008/2007 cell ratios span 0.42–3.38 (1st–99th percentile). Within a year about 5.42M nonzero bit patterns are distinct, with at most 3 repeats of any value. Sampled rows show no proportional copies.
- **Rights.** I fetched the Dataverse v2.1 JSON and the GGDC release page myself and confirmed the CC BY 4.0 text, the unrestricted file and the link to datafile 199103.
- **Novelty.** `novelty.py` on the three resource URLs and on the terms WIOD, input-output, world input, ggdc, leontief, supply-use, icio, eora, exiobase, national accounts, PJ2M1C and dataverse.nl matched only the candidate itself. I inspected the Matrix Market `econaus` neighbour and found it is not equivalent.
