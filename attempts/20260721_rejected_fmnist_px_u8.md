# fmnist_px_u8

- Date: 2026-07-21
- Status: rejected
- Candidate dataset: Fashion-MNIST garment image pixels as uint8.
- Source: https://github.com/zalandoresearch/fashion-mnist
- Why it looked promising: Public MIT-licensed benchmark image corpus with native 8-bit grayscale pixels and about 55 MB of aggregate uncompressed pixel data.
- Failure class: natural_record_below_floor
- What happened: The accepted recipe grouped independent 28x28 images by split and garment class, producing one physical sample per `(split, class)` of concatenated image pixels. The natural records are individual images, each only 784 uint8 values.
- Evidence: `datasets/fmnist_px_u8/manifest.toml` stated that 28x28 images were grouped by `(split, label)` because a single image is below the 1,000-value floor. Local realized output had 20 grouped samples and 54,880,000 primary bytes, but the honest natural-record view would have 70,000 samples of 784 bytes each.
- Decision: Remove `fmnist_px_u8` from `datasets/` and reject it under the same rule as `mnist_px_u8`. Accepting it would require either admitting sub-1 KB natural image records or hiding the true sample geometry through class-level concatenation.
- Retry conditions: Retry only if the repository explicitly changes policy to accept small natural image records below the median-sample floor.
