# google_quickdraw_bitmap_classes_u8

- Date: 2026-07-21
- Status: rejected
- Candidate dataset: Google Quick, Draw! 28x28 bitmap sketch pixels as uint8.
- Source: https://quickdraw.withgoogle.com/data
- Why it looked promising: Public CC-BY crowdsourced sketch corpus with native 8-bit bitmap arrays and hundreds of megabytes of aggregate uncompressed pixel data.
- Failure class: natural_record_below_floor
- What happened: The accepted recipe emitted one physical sample per prompt class by stripping each source NumPy array into a class-level bitmap stack. The natural records are individual drawings, each only 28x28 = 784 uint8 values.
- Evidence: Local realized output had 6 class-stack samples, 697,672,976 primary bytes, and 889,889 drawings. The sample index recorded shapes such as `[151623, 28, 28]` and `natural_record_kind = "quickdraw_bitmap_class"`, which describes an aggregation artifact rather than a source natural record.
- Decision: Remove `google_quickdraw_bitmap_classes_u8` from `datasets/` and reject it under the same rule as `mnist_px_u8` and `fmnist_px_u8`. Accepting it would require either admitting sub-1 KB natural image records or hiding the true sample geometry through prompt-class concatenation.
- Retry conditions: Retry only if the repository explicitly changes policy to accept small natural image/drawing records below the median-sample floor.
