# Fashion-MNIST Images (uint8)

Full Fashion-MNIST image-pixel recipe. The primary payload is the native 28x28 grayscale `uint8` image stream from the official upstream IDX gzip files.

Usage:
```sh
bash datasets/fashion_mnist_images_u8/download.sh
bash datasets/fashion_mnist_images_u8/build.sh
bash datasets/fashion_mnist_images_u8/verify.sh
```

Promote to `datasets/` only after the user-run download and local build/verify path succeeds.
