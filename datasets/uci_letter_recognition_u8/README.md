# UCI Letter Recognition Features (uint8)

UCI Letter Recognition recipe. The primary payload is the native integer OCR feature table, emitted as row-major `uint8` values without local remapping.

Usage:
```sh
bash datasets/uci_letter_recognition_u8/download.sh
bash datasets/uci_letter_recognition_u8/build.sh
bash datasets/uci_letter_recognition_u8/verify.sh
```

Promote to `datasets/` only after the user-run download and local build/verify path succeeds.
