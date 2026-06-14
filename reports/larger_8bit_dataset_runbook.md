# Larger 8-bit Dataset Runbook

These larger native `uint8` recipes have passed user-run download and local build/verify, then were promoted to `datasets/`.

Download commands:

```sh
bash datasets/emnist_byclass_images_u8/download.sh
bash datasets/medmnist_pathmnist_images_u8/download.sh
```

Local build/verify commands:

```sh
bash datasets/emnist_byclass_images_u8/build.sh && bash datasets/emnist_byclass_images_u8/verify.sh
bash datasets/medmnist_pathmnist_images_u8/build.sh && bash datasets/medmnist_pathmnist_images_u8/verify.sh
```

Detailed state report:

```sh
python3 tools/report_dataset_state.py \
  datasets/emnist_byclass_images_u8 \
  datasets/medmnist_pathmnist_images_u8 \
  --output-md reports/larger_8bit_dataset_state.md \
  --output-tsv reports/larger_8bit_dataset_state.tsv
```
