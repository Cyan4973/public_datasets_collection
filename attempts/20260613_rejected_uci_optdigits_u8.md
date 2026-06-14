# uci_optdigits_u8

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: UCI Optical Recognition of Handwritten Digits features
- Source: https://archive.ics.uci.edu/dataset/80/optical+recognition+of+handwritten+digits
- Why it looked promising: Native bounded 8x8 digit feature grids represented as `uint8`.
- Failure class: natural_record_below_floor
- What happened: The recipe emitted train/test block samples. The natural samples are rows with 64 feature values each.
- Evidence: Local natural-boundary audit: 5,620 natural records, 64 values per record, 359,680 physical block values.
- Decision: Removed from `datasets/`; accepting train/test concatenations would mask the true sample geometry.
- Retry conditions: Retry only as part of a policy change that admits short fixed-width rows despite the median-sample floor.
