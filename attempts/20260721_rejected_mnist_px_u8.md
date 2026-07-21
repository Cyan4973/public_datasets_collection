# mnist_px_u8

- Date: 2026-07-21
- Status: rejected
- Candidate dataset: MNIST handwritten digit image pixels as uint8.
- Source: https://storage.googleapis.com/cvdf-datasets/mnist
- Why it looked promising: Public benchmark image corpus with native 8-bit grayscale pixels and large aggregate byte volume.
- Failure class: natural_record_below_floor
- What happened: The accepted recipe grouped independent 28x28 images by split and digit class, producing one physical sample per `(split, class)` of concatenated image pixels. The natural records are individual images, each only 784 uint8 values.
- Evidence: `datasets/mnist_px_u8/manifest.toml` stated that 28x28 images were grouped by `(split, label)` because a single image is below the 1,000-value floor.
- Decision: Remove `mnist_px_u8` from `datasets/` and reject it as uninteresting for this repository's current collection rules. Accepting it would require either admitting sub-1 KB natural image records or hiding the true sample geometry through class-level concatenation.
- Retry conditions: Retry only if the repository explicitly changes policy to accept small natural image records below the median-sample floor.
