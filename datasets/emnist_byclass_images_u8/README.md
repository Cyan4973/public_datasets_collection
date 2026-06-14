# EMNIST ByClass Images (uint8)

Large public-domain handwritten-character image recipe from the official NIST EMNIST archive. The primary payload is the native 28x28 grayscale `uint8` image stream for the ByClass train and test splits.

Usage:
```sh
bash datasets/emnist_byclass_images_u8/download.sh
bash datasets/emnist_byclass_images_u8/build.sh
bash datasets/emnist_byclass_images_u8/verify.sh
```

Promote to `datasets/` only after the user-run download and local build/verify path succeeds.
