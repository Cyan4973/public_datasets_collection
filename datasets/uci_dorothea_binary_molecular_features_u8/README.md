# UCI DOROTHEA binary molecular feature vectors (u8)

Accepted recipe for the DOROTHEA drug-discovery benchmark's documented sparse
binary input matrix. Each chemical compound is one natural record with
100,000 binary molecular features. Sparse one-based feature indices are
losslessly decoded to a 100,000-byte 0/1 vector; compounds and splits are never
concatenated.

The expected source scope is 800 training, 350 validation, and 800 test
compounds, producing 1,950 natural samples and 195,000,000 primary bytes.
Classification labels are excluded.

The official UCI record identifies the dataset license as CC BY 4.0, permitting
training and commercial reuse with attribution.

Sparse binary material is intentionally a new compression shape. The realized
minimum minority fraction is `0.00653`, comfortably above the repository's
`0.001` sparse-binary audit threshold.

## Run

From the repository root:

```bash
bash datasets/uci_dorothea_binary_molecular_features_u8/download.sh
```

After the user-run download succeeds, the local-only steps are:

```bash
bash datasets/uci_dorothea_binary_molecular_features_u8/build.sh
bash datasets/uci_dorothea_binary_molecular_features_u8/verify.sh
```
