# fashion_mnist_images_u8

- Date: 2026-06-13
- Status: rejected
- Candidate dataset: Fashion-MNIST image pixels
- Source: https://github.com/zalandoresearch/fashion-mnist
- Why it looked promising: Native MIT-licensed `uint8` grayscale image pixels with large aggregate volume.
- Failure class: natural_record_below_floor
- What happened: The recipe emitted split-level blocks. The natural samples are individual 28x28 images, only 784 values each.
- Evidence: Local natural-boundary audit: 70,000 natural records, 784 values per record, 54,880,000 physical block values.
- Decision: Removed from `datasets/`; accepting split-level concatenations would mask the true sample geometry.
- Retry conditions: Retry only if the repository explicitly lowers the natural-record median floor for 28x28 grayscale image corpora.
