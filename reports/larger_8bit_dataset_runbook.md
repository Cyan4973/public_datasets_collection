# Larger 8-bit Dataset Runbook

These larger native `uint8` recipes have passed user-run download, local build/verify, and natural-boundary audit, then were promoted to `datasets/`.

Download commands:

```sh
bash datasets/medmnist_pathmnist_images_u8/download.sh
```

Local build/verify commands:

```sh
bash datasets/medmnist_pathmnist_images_u8/build.sh && bash datasets/medmnist_pathmnist_images_u8/verify.sh
```

Detailed state report:

```sh
python3 tools/report_dataset_state.py \
  datasets/medmnist_pathmnist_images_u8 \
  --output-md reports/larger_8bit_dataset_state.md \
  --output-tsv reports/larger_8bit_dataset_state.tsv
```

Rejected after natural-boundary audit:

- `emnist_byclass_images_u8`: aggregate payload is large, but each natural image is 784 values, below the 1,000-value median floor.
