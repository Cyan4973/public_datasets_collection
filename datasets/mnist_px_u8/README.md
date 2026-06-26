# MNIST Pixels (u8)

Grayscale 8-bit pixel intensities of the MNIST handwritten-digit images, as **one family**
with **one sample per (split, digit class)**. Fills a local gap: the downstream corpus has
`mnist_px_28x28`, which our collection lacked (we had CIFAR and PathMNIST, not MNIST).

- Source: https://storage.googleapis.com/cvdf-datasets/mnist (IDX gzip mirror)
- Local raw payloads: `${DATA_DIR:-.data}/downloads/mnist_px_u8/`

## Family & samples

| family | quantity | type |
|---|---|---|
| `mnist_pixel_u8` | grayscale pixel intensity (0–255) | uint8 |

- **A sample** = all pixels of one (split, class) — e.g. all training "7" images concatenated
  row-major. A single 28×28 image is only 784 values (< the 1,000 floor), so pixels are
  grouped per class; train/test are kept separate → 20 samples.

## Run

```sh
bash datasets/mnist_px_u8/download.sh   # 4 IDX gzip files (~11 MB)
bash datasets/mnist_px_u8/build.sh
bash datasets/mnist_px_u8/verify.sh
```

Tuning env vars: `MNIST_BASE` (mirror), `MNIST_MIN_RECORDS` (default 1000). Logs under
`${DATA_DIR:-.data}/logs/mnist_px_u8/`.
