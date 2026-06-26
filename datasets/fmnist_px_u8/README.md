# Fashion-MNIST Pixels (u8)

Grayscale 8-bit pixel intensities of the Fashion-MNIST images, as **one family** with **one
sample per (split, garment class)**. Fills a local gap: the downstream corpus has
`fmnist_px_28x28`, which our collection lacked.

- Source: https://github.com/zalandoresearch/fashion-mnist (IDX gzip, same format as MNIST)
- Local raw payloads: `${DATA_DIR:-.data}/downloads/fmnist_px_u8/`

## Family & samples

| family | quantity | type |
|---|---|---|
| `fmnist_pixel_u8` | grayscale pixel intensity (0–255) | uint8 |

- **A sample** = all pixels of one (split, class) concatenated row-major. A single 28×28 image
  is only 784 values (< the 1,000 floor), so pixels are grouped per class; train/test are kept
  separate → 20 samples. Fashion-MNIST textures fill more of the 0–255 range than MNIST's
  mostly-black-background digits.

## Run

```sh
bash datasets/fmnist_px_u8/download.sh   # 4 IDX gzip files (~31 MB)
bash datasets/fmnist_px_u8/build.sh
bash datasets/fmnist_px_u8/verify.sh
```

Tuning env vars: `FMNIST_BASE` (mirror), `FMNIST_MIN_RECORDS` (default 1000). Logs under
`${DATA_DIR:-.data}/logs/fmnist_px_u8/`.
