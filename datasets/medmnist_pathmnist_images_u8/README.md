# MedMNIST PathMNIST Images (uint8)

Large CC-BY biomedical-image recipe from MedMNIST v2. The primary payload is the native `uint8` RGB histopathology image arrays from `pathmnist.npz`.

Usage:
```sh
bash datasets/medmnist_pathmnist_images_u8/download.sh
bash datasets/medmnist_pathmnist_images_u8/build.sh
bash datasets/medmnist_pathmnist_images_u8/verify.sh
```

Promote to `datasets/` only after the user-run download and local build/verify path succeeds.
