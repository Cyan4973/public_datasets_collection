# mnist_px_28x28

- Date: 2026-06-01
- Status: rejected
- Candidate dataset: MNIST trimmed 28x28 subset
- Source: http://yann.lecun.com/exdb/mnist/
- Why it looked promising: Pixel arrays are numeric, but the external exact ID is a trimmed, review-driven subset rather than a stable upstream acquisition target.
- Failure class: scope_mismatch
- What happened: The external dataset ID encodes a deliberately trimmed subset. This repository should prefer faithful public acquisition recipes over model-gap subset recreations.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Reject the exact external ID for this repo; add a proper full-source MNIST recipe later if needed.
- Retry conditions: Retry only if the repository explicitly decides to admit curated subset recipes.
