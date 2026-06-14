# 8-bit Dataset Runbook

These recipes have passed the user-run download, local build/verify path, and natural-boundary audit, then were promoted to `datasets/`.

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
  --output-md reports/8bit_dataset_state.md \
  --output-tsv reports/8bit_dataset_state.tsv
```

Natural-boundary audit:

```sh
python3 tools/audit_natural_boundaries.py \
  medmnist_pathmnist_images_u8 \
  --output-md reports/8bit_natural_boundary_audit.md \
  --output-tsv reports/8bit_natural_boundary_audit.tsv
```

Removed after review:

- `uci_wireless_indoor_localization_i8`: rejected as too small for the 8-bit collection goal; its primary payload was only 14,000 bytes.
- `fashion_mnist_images_u8`: rejected because natural records are 28x28 grayscale images, 784 values each.
- `emnist_byclass_images_u8`: rejected because natural records are 28x28 grayscale images, 784 values each.
- `uci_letter_recognition_u8`: rejected because natural records are rows of 16 feature values.
- `uci_optdigits_u8`: rejected because natural records are rows of 64 feature values.
- `uci_skin_segmentation_bgr_u8`: rejected because natural records are rows of 3 BGR values.
- `uci_statlog_landsat_satellite_u8`: rejected because natural records are rows of 36 feature values.

Natural-record rule:

- Physical block samples must not be used to pass the median-sample floor when the actual natural record is smaller than 1,000 primary values.
