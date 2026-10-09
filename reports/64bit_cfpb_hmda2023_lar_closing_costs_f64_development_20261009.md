# HMDA 2023 public LAR closing-cost float64 development

## Outcome

Accepted `cfpb_hmda2023_lar_closing_costs_f64` from the pinned FFIEC/CFPB HMDA 2023 Snapshot National Loan-Level Dataset (the privacy-modified public Loan/Application Register).

The recipe emits four separate primary float64 series of per-loan mortgage closing-cost dollar amounts, as reported under Regulation C:

- `hmda2023_total_loan_costs_f64` (`total_loan_costs`, Closing Disclosure section D)
- `hmda2023_origination_charges_f64` (`origination_charges`)
- `hmda2023_discount_points_f64` (`discount_points`, dollars paid to reduce the rate)
- `hmda2023_lender_credits_f64` (`lender_credits`)

It is the first HMDA or consumer-loan-cost material in the corpus. Monetary amounts already exist at 64 bits (SEC FSD i64, NIH award u64, bitcoin output amounts i64, coinpaprika f64), so the novelty is a new source, not a new modality. The zlsim breadth measurement is OK: nearest families are 0.087–0.104 away, and none of them is a money family.

## Source and rights

- Page: https://ffiec.cfpb.gov/data-publication/snapshot-national-loan-level-dataset/2023
- File: https://files.ffiec.cfpb.gov/static-data/snapshot/2023/2023_public_lar_csv.zip
- Zip bytes: 624,535,331 (Last-Modified 2025-11-21)
- Zip SHA-256: `addc78ab14d89ba5ea3169386c514421459f2d59978885c6dbdf54d2a567b19a`
- Member: `2023_public_lar_csv.csv`, Deflate, zip64, 4,339,556,230 bytes, CRC-32 1354180223, 99 columns, header SHA-256 `dbef6042…bd126063`
- Rights: public domain. CFPB's legal notice states "Information created by the CFPB is in the public domain ... you may reproduce, publish, or otherwise use it without the Bureau's permission." The public LAR is compiled and released by CFPB on behalf of the FFIEC because HMDA (12 U.S.C. 2801 et seq.) and Regulation C (12 CFR 1003.5(c)) require public disclosure. No per-file license exists. The precedent for filer-submitted federal statutory data is the accepted `sec_fsd_2015q1_2024q4_numeric_values_i64`.
- Privacy: CFPB applies its public-disclosure modifications before release. Only `state_code` (for partitioning) and the four cost columns are read. No LEI, census tract, demographic or identifier field is emitted.

## Shape and conversion

- The natural record is one LAR row, i.e. one loan.
- A sample is one cost field for one state, with values in national-file order (grouped by reporting institution, not re-sorted).
- Kept tokens must match `^[0-9]+(\.[0-9]+)?$` and are parsed once with `float()` into IEEE-754 binary64, written little-endian.
- `''`, `NA` and `Exempt` (the EGRRCPA partial-exemption marker) are missing.
- Negative and malformed tokens are skipped and counted, and more than 0.1% malformed per field is fatal. The realized counts are 0 negatives and one malformed token each in three fields.
- 240,628 rows with `state_code = NA` are excluded; they drop only 221–1,298 values per field.
- (field, state) groups below 1,000 values (GU and VI in every field) are dropped and listed in `ingest_stats.json`.
- Rounded or binned LAR fields (loan amount, income, DTI, rates, LTV) are excluded.
- float64 is the faithful parse width for cent decimals.

## Accepted output

- Source rows: 11,483,889
- Primary samples: 208 (52 per series: 50 states, DC, PR)
- Primary values: 14,599,409
- Primary bytes: 116,795,272
- Minimum sample: 2,203 values; median 39,869; maximum 523,441

| series | values | bytes | zero share (median / max) |
|---|---|---|---|
| total_loan_costs | 5,052,555 | 40,420,440 | 4.6% / 14.7% |
| origination_charges | 5,111,043 | 40,888,344 | 14.1% / 23.8% |
| discount_points | 2,865,739 | 22,925,912 | 0 / 0 |
| lender_credits | 1,570,072 | 12,560,576 | 0 / 0 |

- Aggregate SHA-256 of sample bytes, concatenated in sorted sample_path order: `5bdd38fbc41b8da289021a6864bff4dba0b066847bcafb98e83670bac108439d`
- Long-tail maxima are kept as reported. Examples: discount_points 999,999.99 (one likely filer placeholder, MI), origination_charges 8,753,933, total_loan_costs 5,989,980.91.

## Judge checks

- **Gate:** `tools/autocollect/gate.py` PASS with no warnings (values 14,599,409, bytes 116,795,272, 208 samples, median 39,869, width 64).
- **Verify:** I ran `verify.sh` myself and it passed (`verify_ok samples=208 bytes=116795272`). It re-parsed all 11,483,889 rows with the byte-split parser (0 quoted rows) and matched every sample SHA-256, count, min/max and zero fraction. `build.sh` reads only the local zip; grep found no curl, http or credential strings in build, verify or the parser.
- **Bytes:** I unpacked every sample with `struct '<d'`.
  - Cent-lattice share is at least 0.99995 in all series. Integer-dollar share is 16.5% (total), 53% (origination), 20% (points) and 45% (credits).
  - Medians are $6,284, $2,175, $3,160 and $250. Distinct ratio per sample is 0.28–0.87.
  - The top origination values ($995, $1,295, $1,440) are typical lender fee schedules.
  - Adjacent-ascending fraction is about 0.42–0.50, so the data is not sorted.
  - Equal runs of 100 or more cover 1.4% (total) and 2.6% (origination) of values and are mostly lender-level zeros.
  - Low-byte entropy is 1.6–4.6 bits, so the f64 is not hollow.
- **Field overlap:** a separate CSV pass found exact row-level equality of 6.5% for total==origination, 9.0% for origination==discount_points, 0.14% for total==discount_points and 0.33% for total==lender_credits. The four series are distinct quantities, not duplicated views.
- **Rights:** I opened the CFPB legal notice and quoted it above. The LAR field-definitions page (fields "in dollars") has no restrictive terms.
- **Novelty:** `novelty.py --url` matched only this staging recipe. The HMDA, FFIEC, mortgage and closing-cost terms matched nothing in recipes, the registry or downstream. `--type/--instrument/--archive` returned 0/0/0. The broad money-term sweep shows existing 64-bit monetary families, hence `new_source`.
- **Fill:** there were no fill warnings. The origination and total zero shares are genuine "no fee" reports, at most 23.8% in any sample.
