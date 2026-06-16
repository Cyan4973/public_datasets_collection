# medRxiv Details 2024

Bounded full-year medRxiv preprint metadata recipe. The repaired recipe replaces
the old January first-page slice with cursor-paginated monthly windows for 2024.

Run:

```bash
datasets/medrxiv_details/download.sh
datasets/medrxiv_details/build.sh
datasets/medrxiv_details/verify.sh
```

Default scope:

- server: `medrxiv`
- year: `2024`
- windows: one cursor-paginated request series per month
- natural sample boundary: one homogeneous metadata field sequence sorted by
  preprint version date
- primary fields: version number, author count, abstract length, title length,
  and corresponding institution field length
- auxiliary field: date, used only for alignment and sort validation

The build deduplicates by DOI/version, rejects malformed rows, rejects constant
primary series, and enforces the repository primary-value, primary-byte,
median-sample, and `1 GB` output limits.
