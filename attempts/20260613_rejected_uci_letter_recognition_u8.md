# uci_letter_recognition_u8

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: UCI Letter Recognition OCR features
- Source: https://archive.ics.uci.edu/dataset/59/letter+recognition
- Why it looked promising: Native bounded integer OCR feature vectors represented as `uint8`.
- Failure class: natural_record_below_floor
- What happened: The recipe emitted one table block. The natural samples are rows with 16 feature values each.
- Evidence: Local natural-boundary audit: 20,000 natural records, 16 values per record, 320,000 physical block values.
- Decision: Removed from `datasets/`; accepting a table-block concatenation would mask the true sample geometry.
- Retry conditions: Retry only as part of a policy change that admits short fixed-width rows despite the median-sample floor.
