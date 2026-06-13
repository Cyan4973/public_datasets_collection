# fred_us_monthly_macro_panel

Status: rejected

Reason:
- the proposed bundle cleared the size floor, but it failed the repository homogeneity rule
- it mixed materially different monthly signals into one panel:
  - labor (`UNRATE`, `UNEMPLOY`, `CLF16OV`, `CIVPART`, `PAYEMS`)
  - prices (`CPIAUCSL`, `CPILFESL`, `PCEPI`, `PPIACO`)
  - real activity (`INDPRO`, `TCU`, `HOUST`)
  - money / policy / sentiment (`M2SL`, `FEDFUNDS`, `UMCSENT`)
- same source family and same cadence were not enough to justify one accepted dataset

Observed fresh build:
- sample files: `15`
- total values: `13,025`
- total bytes: `52,100`

Conclusion:
- do not accept a single mixed FRED macro panel
- any future FRED consolidation must stay homogeneous by material, not merely by source or cadence

