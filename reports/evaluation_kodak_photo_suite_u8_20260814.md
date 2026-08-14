# Kodak photo suite uint8 evaluation benchmark — 2026-08-14

## Outcome

Prepared `kodak_photo_suite_eval_u8` as the repository's first explicitly
evaluation-only numeric family. It is not an accepted training dataset and is
absent from the training attempt registry and accepted-recipe audit.

## Material

The canonical suite contains all 24 `kodim01.png` through `kodim24.png`
photographs:

- 18 landscape images at 768×512;
- 6 portrait images at 512×768;
- 24 lossless, noninterlaced, 8-bit true-color PNG sources;
- 72 separate R, G, and B plane samples;
- 393,216 values per plane; and
- 28,311,552 uint8 values/bytes total.

The pure-standard-library decoder validates every PNG signature, chunk length,
chunk CRC, IHDR field, compressed stream, scanline filter, orientation, and
end marker. Exact source PNG SHA-256 and independently decoded RGB SHA-256
values are pinned in `selection.tsv`. Build output is independently decoded
again and compared byte-for-byte during verification.

All 72 planes are unique and contain 218–256 distinct byte values. Their
zlib-9 ratios range from approximately 0.4295 to 0.9196, with a median near
0.7523.

## Isolation and methodology

Every payload and generated artifact lives under
`.data/evaluation/kodak_photo_suite_eval_u8/`; nothing is written to the
training sample, index, or filtered-data trees. The manifest, summary, and
every index row declare `intended_use=evaluation_only` and
`training_eligible=false`.

Kodak is best described as an unseen classic photographic holdout rather than
strong semantic OOD, because the training corpus already contains other image
planes. Model weights, codec logic, and hyperparameters must be frozen before
measurement. Repeatedly adapting to Kodak would turn it into development data.

## Rights limitation

The suite is ubiquitous in image-compression research, but the canonical
source page does not state a sufficiently explicit permissive license for
training or redistribution. The recipe therefore records rights status as
`unclear`, keeps payloads local, and makes no rights grant. This historical
benchmark-use rationale must not be generalized into permission to train on or
redistribute the images.
