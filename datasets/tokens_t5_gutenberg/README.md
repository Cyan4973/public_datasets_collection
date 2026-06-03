`tokens_t5_gutenberg` emits one raw `uint16` little-endian Unigram token-ID stream per pinned Project Gutenberg book.

Scope:
- same 12 Gutenberg books used in the sibling public-datasets repo
- `google-t5/t5-small` `tokenizer.json`
- deterministic Gutenberg boilerplate stripping
- stdlib-only whitespace + metaspace + Unigram Viterbi tokenization

Files:
- `download.sh` fetches `tokenizer.json` and the 12 books
- `build.sh` tokenizes and emits one sample per book
- `verify.sh` checks raw inputs, sample sizes, and `samples.jsonl`

Output:
- series id: `tokens_t5_ids`
- numeric type: `uint16`
- endianness: little
- one sample per book
