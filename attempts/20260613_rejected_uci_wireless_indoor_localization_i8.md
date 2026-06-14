# uci_wireless_indoor_localization_i8

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: UCI Wireless Indoor Localization RSSI
- Source: https://archive.ics.uci.edu/dataset/422/wireless+indoor+localization
- Why it looked promising: Native signed 8-bit WiFi RSSI measurements from a distinct sensor domain.
- Failure class: below_floor
- What happened: The primary payload contained only 14,000 signed 8-bit RSSI values, totaling 14,000 bytes.
- Evidence: Local build/verify succeeded, but the realized primary byte size was far below the 100 KiB floor expected for 8-bit additions.
- Decision: Removed from `datasets/`; do not accept as an 8-bit compression-training recipe.
- Retry conditions: Retry only if a materially broader WiFi RSSI corpus is used, not this intrinsically small standalone table.
