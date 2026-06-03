`unicode_bmp_gutenberg` emits one raw `uint16` little-endian code-unit stream per pinned Project Gutenberg book.

Scope:
- same 12 Gutenberg books used by the sibling token datasets
- Project Gutenberg boilerplate stripped deterministically
- output is UTF-16LE code units exactly as encoded from the stripped text

Files:
- `download.sh` downloads the 12 books into `${DATA_DIR:-.data}/downloads/unicode_bmp_gutenberg/texts/`
- `build.sh` strips boilerplate and writes one sample per book
- `verify.sh` checks the raw inventory, sample sizes, and `samples.jsonl`

Output:
- series id: `unicode_bmp_codeunits`
- numeric type: `uint16`
- endianness: little
- one sample per book
