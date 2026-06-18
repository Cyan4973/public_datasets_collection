# SEC Dataset State - 2026-06-17

Current accepted SEC datasets:

- `sec_fsd_2015q1_2024q4_numeric_values_i64`
- `sec_submissions_largecap_bundle`

Superseded SEC shapes:

- `sec_fsd_2024q1_q4_numeric_values_i64` was replaced by the 10-year FSD
  recipe to avoid duplicate SEC FSD training material.

Rejected SEC shapes:

- `sec_companyfacts_*` single-metric recipes were removed because issuer-fact
  quarterly natural samples had only `32-51` values and failed the median
  natural-sample floor.
- SEC submissions single-issuer or two-issuer slices were superseded by
  `sec_submissions_largecap_bundle`.
- Local categorical filing-form remaps are not primary numeric training
  material. `sec_submission_form_code` was removed from the accepted submissions
  bundle; form strings are retained only as validation fields.

## `sec_fsd_2015q1_2024q4_numeric_values_i64`

- status: accepted and verified
- source: official SEC Financial Statement Data Sets quarterly ZIP files
- scope: `2015q1` through `2024q4`
- natural sample boundary: one quarterly `num.txt` value column restricted by
  exact SEC `tag` and exact `uom`
- primary series: 20 selected high-volume homogeneous tag/unit streams
- primary samples: `787`
- primary values: `22,524,021`
- primary bytes: `180,192,168`
- median primary sample values: `16,419`
- min/max primary sample values: `40` / `180,483`
- source bytes: `3,795,297,731`
- note: `RevenueFromContractWithCustomerExcludingAssessedTax` is absent from
  `2015q1` through `2018q1`; those empty tag/quarter streams are not emitted.

Selected `SHARES` streams:

| series | samples | total values | bytes | value count range | median values |
|---|---:|---:|---:|---:|---:|
| `sec_fsd_shares_common_stock_shares_authorized_i64` | 40 | 612,885 | 4,903,080 | 12,149-20,771 | 14,875.0 |
| `sec_fsd_shares_common_stock_shares_issued_i64` | 40 | 683,573 | 5,468,584 | 12,702-22,472 | 16,090.0 |
| `sec_fsd_shares_common_stock_shares_outstanding_i64` | 40 | 829,934 | 6,639,472 | 13,154-30,226 | 19,226.5 |
| `sec_fsd_shares_investment_owned_balance_shares_i64` | 40 | 76,645 | 613,160 | 40-9,472 | 59.5 |
| `sec_fsd_shares_preferred_stock_shares_authorized_i64` | 40 | 408,360 | 3,266,880 | 7,890-13,818 | 9,988.0 |
| `sec_fsd_shares_preferred_stock_shares_outstanding_i64` | 40 | 335,129 | 2,681,032 | 6,416-11,415 | 7,749.5 |
| `sec_fsd_shares_shares_outstanding_i64` | 40 | 660,519 | 5,284,152 | 4,325-35,333 | 16,596.0 |
| `sec_fsd_shares_stock_issued_during_period_shares_new_issues_i64` | 40 | 323,181 | 2,585,448 | 2,561-13,762 | 8,527.5 |
| `sec_fsd_shares_weighted_average_number_of_diluted_shares_outstanding_i64` | 40 | 531,424 | 4,251,392 | 7,180-23,739 | 11,854.5 |
| `sec_fsd_shares_weighted_average_number_of_shares_outstanding_basic_i64` | 40 | 565,957 | 4,527,656 | 7,492-26,584 | 12,275.0 |

Selected `USD` streams:

| series | samples | total values | bytes | value count range | median values |
|---|---:|---:|---:|---:|---:|
| `sec_fsd_usd_assets_i64` | 40 | 1,271,965 | 10,175,720 | 26,480-42,594 | 30,583.5 |
| `sec_fsd_usd_investment_owned_at_cost_i64` | 40 | 682,067 | 5,456,536 | 484-95,335 | 842.0 |
| `sec_fsd_usd_investment_owned_at_fair_value_i64` | 40 | 839,830 | 6,718,640 | 1,478-110,033 | 2,541.5 |
| `sec_fsd_usd_investment_owned_balance_principal_amount_i64` | 40 | 490,247 | 3,921,976 | 383-66,623 | 777.5 |
| `sec_fsd_usd_net_income_loss_i64` | 40 | 2,159,203 | 17,273,624 | 34,157-80,035 | 51,873.5 |
| `sec_fsd_usd_operating_income_loss_i64` | 40 | 1,443,776 | 11,550,208 | 24,427-47,288 | 36,294.5 |
| `sec_fsd_usd_revenue_from_contract_with_customer_excluding_assessed_tax_i64` | 27 | 2,488,359 | 19,906,872 | 5,129-117,590 | 96,927.0 |
| `sec_fsd_usd_revenues_i64` | 40 | 1,765,255 | 14,122,040 | 24,612-64,334 | 43,558.5 |
| `sec_fsd_usd_stockholders_equity_i64` | 40 | 4,032,001 | 32,256,008 | 44,435-180,483 | 99,490.5 |
| `sec_fsd_usd_stockholders_equity_including_portion_attributable_to_noncontrolling_interest_i64` | 40 | 2,323,711 | 18,589,688 | 30,845-89,881 | 59,036.0 |

## `sec_submissions_largecap_bundle`

- status: accepted and verified
- source: official SEC `data.sec.gov/submissions/CIK*.json` payloads
- scope: `49` tracked large-cap issuers in
  `datasets/sec_submissions_largecap_bundle/issuers.tsv`
- natural sample boundary: one issuer-column filing-metadata array
- primary series: `sec_submission_size`,
  `sec_submission_acceptance_timestamp`, `sec_submission_xbrl_flag`,
  `sec_submission_inline_xbrl_flag`, `sec_submission_filing_date_ordinal`
- primary samples: `245`
- primary values: `483,235`
- primary bytes: `1,739,646`
- median primary sample values: `1,001`

## Validation Commands

```bash
bash datasets/sec_submissions_largecap_bundle/build.sh
bash datasets/sec_submissions_largecap_bundle/verify.sh
bash datasets/sec_fsd_2015q1_2024q4_numeric_values_i64/verify.sh
python3 tools/audit_acceptance.py
```
