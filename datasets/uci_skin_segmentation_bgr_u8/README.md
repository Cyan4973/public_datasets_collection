# UCI Skin Segmentation BGR Pixels (uint8)

UCI Skin Segmentation recipe. The primary payload is native 8-bit BGR color-channel measurements from the skin/non-skin table, emitted row-major without remapping.

Usage:
```sh
bash datasets/uci_skin_segmentation_bgr_u8/download.sh
bash datasets/uci_skin_segmentation_bgr_u8/build.sh
bash datasets/uci_skin_segmentation_bgr_u8/verify.sh
```

Promote to `datasets/` only after the user-run download and local build/verify path succeeds.
