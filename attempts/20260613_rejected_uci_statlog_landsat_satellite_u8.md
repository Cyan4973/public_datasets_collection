# uci_statlog_landsat_satellite_u8

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: UCI Statlog Landsat Satellite features
- Source: https://archive.ics.uci.edu/dataset/146/statlog+landsat+satellite
- Why it looked promising: Native bounded remote-sensing feature rows represented as `uint8`.
- Failure class: natural_record_below_floor
- What happened: The recipe emitted train/test block samples. The natural samples are rows with 36 spectral-neighborhood values each.
- Evidence: Local natural-boundary audit: 6,435 natural records, 36 values per record, 231,660 physical block values.
- Decision: Removed from `datasets/`; accepting train/test concatenations would mask the true sample geometry.
- Retry conditions: Retry only with a raster/tile source where each natural sample clears the median floor.
