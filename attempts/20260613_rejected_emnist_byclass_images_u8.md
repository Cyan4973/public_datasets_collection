# emnist_byclass_images_u8

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: EMNIST ByClass image pixels
- Source: https://www.nist.gov/itl/products-and-services/emnist-dataset
- Why it looked promising: Native public-domain `uint8` handwritten-character pixels with large aggregate volume.
- Failure class: natural_record_below_floor
- What happened: The recipe emitted train/test block samples. The natural samples are individual 28x28 images, only 784 values each.
- Evidence: Local natural-boundary audit: 814,255 natural records, 784 values per record, 638,375,920 physical block values.
- Decision: Removed from `datasets/`; accepting split-level concatenations would mask the true sample geometry.
- Retry conditions: Retry only if the repository explicitly lowers the natural-record median floor for 28x28 grayscale image corpora.
