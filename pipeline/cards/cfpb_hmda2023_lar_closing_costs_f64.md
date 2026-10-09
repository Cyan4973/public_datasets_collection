# CFPB/FFIEC HMDA 2023 Snapshot National Loan-Level Dataset: Per-Loan Closing-Cost Dollar Amounts (total_loan_costs, origination_charges, discount_points, lender_credits) Float64

- Candidate id: `cfpb_hmda2023_lar_closing_costs_f64`
- Width: float64
- Quantity: Per-loan mortgage closing-cost amounts in US dollars with cents, as reported under Regulation C for closed-end originations: total loan costs, origination charges, discount points and lender credits. These are four separate primary series, all in USD on a 0.01 lattice.
- Source: https://ffiec.cfpb.gov/data-publication/snapshot-national-loan-level-dataset/2023
- Resources: https://files.ffiec.cfpb.gov/static-data/snapshot/2023/2023_public_lar_csv.zip
- License: Public domain (U.S. Government work, CFPB)
- License evidence: https://www.consumerfinance.gov/privacy/website-privacy-policy/
- License quote: Information created by the CFPB is in the public domain ... consider appropriate citation to the Bureau as the source.
- Natural record: One loan-application record (LAR row). A sample is all records of one state (state_code) in the 2023 national snapshot, with one series per cost field. Values are emitted in file order; 'NA', 'Exempt' and empty values are skipped.
- Estimated samples: 54
- Estimated primary values: 12,700,000
- Estimated download bytes: 624,535,331
- Estimated primary bytes: 101,600,000
- Decode path: curl the pinned snapshot zip (624,535,331 bytes; a single Deflate member '2023_public_lar_csv.csv' >4 GB with a zip64 extra field). Stream it with Python zipfile.ZipFile.open() into csv.DictReader. Group by state_code, parse the four cost columns with float(), skipping NA/Exempt/'' values, and emit little-endian '<d' arrays per state per field. Pure stdlib.
- Novelty kind: new_source
- Measurement type: consumer_loan_cost_amounts
- Instrument line: HMDA Loan/Application Register (Regulation C) public snapshot
- Archive collection: ffiec_cfpb_hmda_snapshot
- Novelty evidence: novelty.py --url on files.ffiec.cfpb.gov returned no URL matches, and the terms hmda / 'loan costs' / mortgage / ffiec matched no recipes, registry rows, ledger entries or downstream families. --type loan_record_values --archive cfpb_hmda_snapshot gave 0/0. The nearest 64-bit relatives are sec_fsd i64 statement values (firm-level integer totals) and downstream nih_award_amount_u64 (integer award totals). None are consumer-loan closing costs, and none are cent-lattice float amounts.
- Homogeneity: Each series is one quantity (USD, 2-decimal cents lattice) from one reporting regime (HMDA 2023 Regulation C LAR), split by state. The four cost fields are kept as separate series, not mixed. interest_rate, LTV, loan_amount (rounded to $10k midpoints), income (thousands) and categorical codes are excluded because they are rounded or proxy fields.
- Risks: (1) A Vermont probe shows origination_charges has about 23% exact zeros and about 70% integer-dollar values, so some cent-lattice regularity could reduce entropy; total_loan_costs is richer (6,055 distinct values in 7,990 rows). (2) Extraction ratio: about 100 MB is kept from about 4.3 GB of uncompressed CSV, but the absolute signal is large and no leaner official source exists (the data-browser per-state CSVs are uncompressed and larger in total). (3) The public LAR is a privacy-modified government release, and only cost amounts are extracted, so no personal identifiers are involved. A judge may still ask about sensitivity. (4) Public-domain status rests on CFPB's general site notice rather than a per-file license; the data is compiled and published by CFPB/FFIEC under statute.
- Probe evidence: HEAD on the 2023 snapshot zip returned 200 with content-length 624535331, and a one-byte range GET with -L returned 206. A tail range read of the central directory shows method 8 (Deflate), csz 624,535,067, usz 0xFFFFFFFF (zip64) and member '2023_public_lar_csv.csv'. The 2022 (877,742,261 B) and 2024 (664,242,987 B) snapshots also exist. I fetched the full Vermont 2023 data-browser CSV (7.2 MB, 18,900 rows): total_loan_costs had 7,990 non-NA values (564 zeros, max 58,801.83), origination_charges 8,228, discount_points 2,675, lender_credits 2,315. Example values: 6748.00, 11673.10, 7923.43.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_110429.jsonl`).
