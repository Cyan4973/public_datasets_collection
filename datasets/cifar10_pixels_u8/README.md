# CIFAR-10 RGB Pixel Intensities (uint8)

Native **8-bit** RGB pixel intensities from CIFAR-10, organized as **one family** (pixel
intensity) with **one sample per 32×32 single-channel plane**. A full-scale recipe
equivalent of the downstream `cifar10_rgb_32x32` token dataset (which holds only 20 images
as per-channel planes); same per-channel layout, all 60,000 images. Values are genuine
pixel *intensities* (0–255), a numeric quantity.

- Source: https://www.cs.toronto.edu/~kriz/cifar.html (binary distribution)
- Local raw payload: `${DATA_DIR:-.data}/downloads/cifar10_pixels_u8/cifar-10-binary.tar.gz`

## Families & samples

| family | quantity | type |
|---|---|---|
| `cifar_pixel_u8` | RGB pixel intensity (0–255) | uint8 |

- **A sample** = one 32×32 single-channel plane (1024 values). Each image yields three
  planes (R, G, B); the leading categorical class-label byte is dropped (a label is not an
  intensity). Sample files are named `{class}_{NN}_{r|g|b}_32x32.bin`, matching the existing
  dataset's convention.
- **Samples/family** ≈ 180,000 (60,000 images × 3 channels; 50k train + 10k test).
- R/G/B are the same quantity (intensity) and share one family — distinguished by a
  `channel` field, not split into three families.

## Run

```sh
bash datasets/cifar10_pixels_u8/download.sh   # one ~170 MB tar.gz, liveness-checked
bash datasets/cifar10_pixels_u8/build.sh
bash datasets/cifar10_pixels_u8/verify.sh
```

Tuning env vars: `CIFAR10_URL` (override), `CIFAR_MAX_IMAGES` (default 60000). Logs under
`${DATA_DIR:-.data}/logs/cifar10_pixels_u8/`.
