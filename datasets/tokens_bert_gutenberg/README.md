`tokens_bert_gutenberg` emits one raw `uint16` little-endian WordPiece token-ID stream per pinned Project Gutenberg book.

Scope:
- same 12 Gutenberg books used in the sibling public-datasets repo
- `google-bert/bert-base-uncased` `vocab.txt`
- deterministic Gutenberg boilerplate stripping
- stdlib-only lowercase + accent stripping + punctuation split + greedy WordPiece

Files:
- `download.sh` fetches `vocab.txt` and the 12 books
- `build.sh` tokenizes and emits one sample per book
- `verify.sh` checks raw inputs, sample sizes, and `samples.jsonl`

Output:
- series id: `tokens_bert_ids`
- numeric type: `uint16`
- endianness: little
- one sample per book
