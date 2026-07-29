# Bitcoin Block Output Amounts Int64 Development — 2026-07-29

`bitcoin_block_output_amounts_i64` adds raw distributed-ledger transaction
structure to the 64-bit corpus. Existing cryptocurrency recipes describe
exchange prices and trades; this recipe instead decodes consensus-serialized
monetary values from immutable blockchain records.

The inventory started from committed `datasets/*/manifest.toml`,
`attempts/dataset_status.tsv`, and `reports/accepted_recipe_audit.tsv`. Hashes
are used only for provenance and integrity. No block hash, transaction hash,
script, or address enters the primary samples.

## Source and native representation

The recipe pins Bitcoin mainnet heights `840000` through `840011` to their
exact block hashes. Raw blocks are retrieved from Blockstream's public Esplora
API. The twelve source objects total `18,874,397` bytes; their exact block
hash, byte-size, and SHA-256 mapping is frozen in `download.sh` and reproduced
in the local download plan.

Bitcoin serializes each transaction output's `nValue` as a native eight-byte
little-endian signed integer. The parser copies those eight bytes unchanged
after requiring a nonnegative value no greater than Bitcoin's `MAX_MONEY`.

The source material is public factual blockchain data. The manifest records a
custom public-data license basis, cites the Blockstream API and Bitcoin
protocol, and excludes scripts and identifiers from the output.

## Protocol validation

The stdlib-only decoder supports legacy and SegWit transactions and enforces:

- canonical CompactSize integers and bounded vector lengths
- complete input, output, script, witness, and locktime parsing
- exact block byte consumption and transaction counts
- filename/pinned hash agreement with the double-SHA256 block header
- reconstructed non-witness transaction IDs and the block's Merkle root
- valid signed-int64 `MoneyRange` output amounts

The user ran the exploratory downloader, after which exact hashes, sizes, and
SHA-256 values were frozen. The user then reran the pinned downloader; all
twelve cached blocks passed exact-source and semantic validation.

## Realized output

Build and independent source-to-output verification passed:

- block samples: `12`
- transactions per block: `2,823` to `5,673`
- outputs per block: `9,716` to `17,560`
- primary values: `168,392`
- primary bytes: `1,347,136`
- median sample: `14,592.5` values
- observed amount range: `0` to `542,409,988,070` satoshis

Zero-valued outputs account for roughly `16.9%` to `36.4%` per block, and
adjacent repeats range from `2.4%` to `17.8%`. Raw per-block deflate ratios
range from `0.1767` to `0.2428`, with an aggregate ratio of `0.1989`.
Independent verification reparses every block and byte-compares every emitted
amount.
