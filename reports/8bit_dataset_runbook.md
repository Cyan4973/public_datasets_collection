# 8-bit Dataset Runbook

These recipes have passed the user-run download and local build/verify path and have been promoted to `datasets/`.

Download commands:

```sh
bash datasets/fashion_mnist_images_u8/download.sh
bash datasets/uci_letter_recognition_u8/download.sh
bash datasets/uci_optdigits_u8/download.sh
bash datasets/uci_statlog_landsat_satellite_u8/download.sh
bash datasets/uci_skin_segmentation_bgr_u8/download.sh
```

Local build/verify commands:

```sh
bash datasets/fashion_mnist_images_u8/build.sh && bash datasets/fashion_mnist_images_u8/verify.sh
bash datasets/uci_letter_recognition_u8/build.sh && bash datasets/uci_letter_recognition_u8/verify.sh
bash datasets/uci_optdigits_u8/build.sh && bash datasets/uci_optdigits_u8/verify.sh
bash datasets/uci_statlog_landsat_satellite_u8/build.sh && bash datasets/uci_statlog_landsat_satellite_u8/verify.sh
bash datasets/uci_skin_segmentation_bgr_u8/build.sh && bash datasets/uci_skin_segmentation_bgr_u8/verify.sh
```

Detailed state report:

```sh
python3 tools/report_dataset_state.py \
  datasets/fashion_mnist_images_u8 \
  datasets/uci_letter_recognition_u8 \
  datasets/uci_optdigits_u8 \
  datasets/uci_statlog_landsat_satellite_u8 \
  datasets/uci_skin_segmentation_bgr_u8 \
  --output-md reports/8bit_dataset_state.md \
  --output-tsv reports/8bit_dataset_state.tsv
```

Removed after review:

- `uci_wireless_indoor_localization_i8`: rejected as too small for the 8-bit collection goal; its primary payload was only 14,000 bytes.

Replacement candidate pending user-run download:

- `uci_optdigits_u8` was downloaded by the user, verified locally, and promoted to `datasets/`.
