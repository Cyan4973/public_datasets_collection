# uci_skin_segmentation_bgr_u8

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: UCI Skin Segmentation BGR channel values
- Source: https://archive.ics.uci.edu/dataset/229/skin+segmentation
- Why it looked promising: Native `uint8` BGR color-channel measurements with moderate aggregate volume.
- Failure class: natural_record_below_floor
- What happened: The recipe emitted one table block. The natural samples are rows with 3 BGR values each.
- Evidence: Local natural-boundary audit: 245,057 natural records, 3 values per record, 735,171 physical block values.
- Decision: Removed from `datasets/`; accepting a table-block concatenation would mask the true sample geometry.
- Retry conditions: Retry only if a broader image-level source is used where each natural image/patch clears the median floor.
