# UCI DOROTHEA Binary Features Development — 2026-07-30

`uci_dorothea_binary_molecular_features_u8` adds high-dimensional sparse
binary molecular descriptors to the 8-bit corpus. Existing byte-valued
materials include spatial rasters, amplitudes, categorical timelines,
biological symbols, quality scores, and quantized weights. DOROTHEA instead
provides one very wide feature-presence vector per chemical compound.

The inventory started from committed `datasets/*/manifest.toml`,
`attempts/dataset_status.tsv`, and `reports/accepted_recipe_audit.tsv`. No
corpus membership or coverage decision used `.data/samples/`.

## Source and license

The source is DOROTHEA, UCI Machine Learning Repository dataset 169. The
official UCI record identifies its license as CC BY 4.0, permitting training
and commercial reuse with attribution. The material is an anonymous public
drug-discovery benchmark with no patient or human-subject information.

The official `5,055,101`-byte ZIP contains three sparse input matrices:

- training: `800` compound rows
- validation: `350` compound rows
- test: `800` compound rows

Classification labels are excluded. All `1,950` feature rows are retained.

## Representation and natural records

UCI documents DOROTHEA as a sparse binary matrix with `100,000` input
features. Each source row lists the one-based positions whose feature value is
one; positions not listed are zeros. Decoding the index list to its equivalent
100,000-position 0/1 vector is therefore a lossless decoding of the documented
matrix, not a local feature mapping or artificial numericization.

Each compound row is one natural sample. The recipe does not concatenate rows
or splits. Download validation requires all three exact matrices, their
documented row counts, ASCII integer indices within `1..100000`, and strictly
increasing unique indices. Build independently repeats those checks before
writing a raw `uint8` vector.

## Sparse-binary gate

The repository's quality audit flags binary samples whose minority fraction is
below `0.001`. DOROTHEA clears that threshold for every compound:

- minimum active features: `653` (`0.00653`)
- median active features: `787` (`0.00787`)
- maximum active features: `11,495` (`0.11495`)
- aggregate active features: `1,776,363`
- aggregate one fraction: `0.00910955`

Thus the vectors are intentionally sparse but not effectively constant under
the corpus policy.

## Realized output

Build and independent verification passed:

- natural samples: `1,950`
- values per sample: `100,000`
- primary values and bytes: `195,000,000`
- values: exactly `{0, 1}` in every sample
- split counts: `800 / 350 / 800`
- output cap: comfortably below `1,000,000,000` bytes

Compressing each sample independently with raw DEFLATE level 9 produces
`2,808,825` bytes from `195,000,000` input bytes, an aggregate ratio of
`0.01440423`. This provides a substantially different sparse-vector training
shape while retaining meaningful variation in descriptor density.
