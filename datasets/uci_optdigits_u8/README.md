# UCI Optdigits Features (uint8)

UCI Optical Recognition of Handwritten Digits recipe. The primary payload is the native bounded integer 8x8 image-feature table, emitted as row-major `uint8` values without local remapping.

Usage:
```sh
bash datasets/uci_optdigits_u8/download.sh
bash datasets/uci_optdigits_u8/build.sh
bash datasets/uci_optdigits_u8/verify.sh
```

Promote to `datasets/` only after the user-run download and local build/verify path succeeds.
