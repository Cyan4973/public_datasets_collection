# Kodak Photo Suite U8 — evaluation-only draft

This recipe prepares the classic 24-image Kodak lossless true-color suite as
an unseen photographic compression benchmark. It is deliberately excluded
from the accepted training corpus because the canonical source does not state
a sufficiently explicit permissive training license.

Hard isolation rules:

- outputs live only under `.data/evaluation/kodak_photo_suite_eval_u8/`;
- no output is written under `.data/samples/` or `.data/index/`;
- the recipe must never be registered as an accepted training dataset;
- source images and decoded planes are not committed or redistributed; and
- model, codec, and hyperparameters must be frozen before evaluation.

Acquire the canonical PNGs with:

```bash
bash evaluation/kodak_photo_suite_eval_u8/download.sh
```

The source is expected to contain 24 lossless 768×512 or 512×768, 8-bit RGB PNGs. After
source identities are pinned, the recipe will emit one row-major uint8 sample
per R, G, or B plane: 72 samples and 28,311,552 bytes total.

After acquisition:

```bash
bash evaluation/kodak_photo_suite_eval_u8/inspect.sh
bash evaluation/kodak_photo_suite_eval_u8/build.sh
bash evaluation/kodak_photo_suite_eval_u8/verify.sh
```
