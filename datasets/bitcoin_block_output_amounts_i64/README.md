# Bitcoin block output amounts — int64

This draft decodes native transaction-output values from twelve historical
Bitcoin blocks beginning at height 840,000. Each output amount is serialized by
the Bitcoin protocol as an eight-byte little-endian signed integer number of
satoshis.

The natural sample is one block's ordered output-value stream. Transaction IDs,
block hashes, scripts, addresses, and other serialized bytes are excluded from
the primary corpus. Hashes are used only to verify provenance and Merkle-tree
integrity.

The source data are public factual records from the Bitcoin blockchain,
retrieved through the Blockstream Esplora public API. The recipe retains only
numeric monetary amounts and cites the API provider and Bitcoin protocol.

## Run

```bash
bash datasets/bitcoin_block_output_amounts_i64/download.sh
bash datasets/bitcoin_block_output_amounts_i64/build.sh
bash datasets/bitcoin_block_output_amounts_i64/verify.sh
```

The recipe pins the immutable hashes, raw source sizes, and SHA-256 values for
heights `840000` through `840011`. The downloader no longer depends on dynamic
height resolution.
