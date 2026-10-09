# cfpb_hmda2023_lar_closing_costs_f64

Per-loan mortgage closing-cost dollar amounts from the FFIEC/CFPB **HMDA 2023
Snapshot National Loan-Level Dataset**, the privacy-modified public Loan/Application
Register (LAR). The recipe emits four primary float64 series, one per cost field.
Each sample holds all kept values of one field for one state, in source row order.

| series | LAR column | meaning |
|---|---|---|
| `hmda2023_total_loan_costs_f64` | `total_loan_costs` | Total Loan Costs (Closing Disclosure section D), USD |
| `hmda2023_origination_charges_f64` | `origination_charges` | borrower-paid itemized origination charges, USD |
| `hmda2023_discount_points_f64` | `discount_points` | points paid to reduce the interest rate, USD |
| `hmda2023_lender_credits_f64` | `lender_credits` | lender credits, USD |

## Source

- Page: https://ffiec.cfpb.gov/data-publication/snapshot-national-loan-level-dataset/2023
- File: https://files.ffiec.cfpb.gov/static-data/snapshot/2023/2023_public_lar_csv.zip,
  624,535,331 bytes, Last-Modified 2025-11-21. It holds a single Deflate member,
  `2023_public_lar_csv.csv`, of 4,339,556,230 bytes (zip64), CRC-32 1354180223,
  with 99 columns.
- Field definitions: https://ffiec.cfpb.gov/documentation/publications/loan-level-datasets/lar-data-fields
  (for example, total_loan_costs is "The amount, in dollars, of total loan costs").

## Rights

HMDA loan-level data is published by CFPB on behalf of the FFIEC because the
Home Mortgage Disclosure Act (12 U.S.C. 2801 et seq.) and Regulation C
(12 CFR 1003.5(c)) require public disclosure. CFPB's legal notice
(https://www.consumerfinance.gov/privacy/website-privacy-policy/) states:
"Information created by the CFPB is in the public domain ... you may reproduce,
publish, or otherwise use it without the Bureau's permission. Please consider
appropriate citation to the Bureau as the source." The extracted values are
factual dollar amounts.

Caveat: there is no per-file license document. The grant rests on the site
notice plus the statutory public-release status. The CFPB documentation repository
(`cfpb/hmda-combined-documentation`) is CC0-1.0, but that covers the docs, not the data.

Privacy: this is the public LAR, with CFPB's Regulation C public-disclosure
modifications already applied, so it has no names, addresses, application dates or
loan IDs. The recipe reads only `state_code`, used for partitioning, and the
four cost columns. No LEI, tract, demographic or other quasi-identifier is emitted.

## Conversion

1. `download.sh` fetches the zip with resumable curl and checks its exact size.
   It prints the SHA-256 (pinned once known) and runs `hmda_costs.py validate`.
   That step checks for exactly one member with the pinned name, size and CRC,
   streams the whole member so that zipfile verifies the CRC-32, and checks the
   SHA-256 of the 99-column header line.
2. `build.sh` streams the CSV with `csv.reader`. A kept token must match
   `^[0-9]+(\.[0-9]+)?$` and is parsed with `float()` into binary64.
   - `''`, `NA` and `Exempt` count as missing. Negative and malformed tokens are
     skipped and counted, and more than 0.1% malformed tokens per field is fatal.
   - Rows with `state_code == NA` are excluded.
   - Each (field, state) group with at least 1,000 values is written as
     `samples/<id>/<series>/<STATE>.f64le.bin` ('<d', file order).
   - Smaller groups (territories, and small states for the sparse
     points/credits fields) are listed in `filtered/<id>/ingest_stats.json`.
   - Index rows also carry `state_code`, `min`, `max`, `zero_fraction`,
     `distinct_values` and `sha256`.
3. `verify.sh` re-parses the CSV with an independent byte-split parser, which
   falls back to `csv` only for quoted lines. It applies the same token policy,
   then re-derives each sample's bytes, hash, count, min/max and zero fraction.
   It checks that the realized sample set matches the index and the manifest
   totals, and rejects samples that are constant, have fewer than 50 distinct
   values, or are more than 90% zeros.

## Scope and expectations

- Width: values are cent-lattice decimals, and most cent fractions are not exact
  in float32, so binary64 is the faithful parse. Byte content is dominated by
  dollar magnitude and cent fraction. `origination_charges` has many exact zeros
  (about 23% in a Vermont probe) and many integer-dollar values. Each index row
  reports its zero share.
- Rows inside each state appear in the national file's order, which is grouped
  by reporting institution (LEI). That order is preserved, not re-sorted.
- The four fields share one unit (USD), one lattice (0.01) and one reporting
  regime (HMDA 2023 Regulation C). They are kept as separate series and never
  mixed. Rounded or binned LAR fields (loan_amount, property_value, income, DTI)
  and rates/ratios are deliberately excluded.
- Realized scope (build of 2026-10-09): 208 samples, 14,599,409 values,
  116,795,272 bytes. Each series has 52 samples: 50 states, DC and PR. GU and VI
  fall below 1,000 values in every field and are dropped.
  - Kept values per series: total_loan_costs 5,052,555; origination_charges
    5,111,043; discount_points 2,865,739; lender_credits 1,570,072.
  - Per-sample sizes run from 2,203 values (lender_credits, smallest state) to
    523,441 (origination_charges, largest state).
  - Zero share per sample: total_loan_costs 0.02%–14.7% (median 4.6%);
    origination_charges 1.6%–23.8% (median 14.1%). discount_points and
    lender_credits contain no zeros, because the source leaves them blank or NA
    when nothing was paid.
  - Skipped tokens: of 11,483,889 rows, 240,628 have state_code NA. One
    malformed token each was skipped in total_loan_costs, discount_points and
    lender_credits. No negative values occur.
  - A few values have more than 2 decimals (148 in discount_points, 4 in the other
    fields). They are kept as parsed.
  - Long-tail maxima (for example, discount_points 999,999.99 and
    origination_charges 8.75M) are kept as reported, without outlier clipping.
