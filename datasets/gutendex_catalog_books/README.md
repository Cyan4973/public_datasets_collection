# Gutendex Catalog Books

Replacement for the below-floor `gutendex_books` first-page search recipe.

This recipe downloads the full Gutendex book catalog in stable ascending order
and emits native numeric metadata:

- `gutendex_download_count_u32`: primary book-table `download_count` values.
- `gutendex_author_birth_year_i16`: primary author birth years from nested
  author records.
- `gutendex_author_death_year_i16`: primary author death years from nested
  author records.
- `gutendex_book_id_u32`: auxiliary book IDs used for alignment/provenance, not
  acceptance.

Natural sample boundaries:

- one full catalog book-table column for `download_count`
- one full catalog author-record column for each author year field

Validated local material:

- source pages: 2,460
- source rows/books: 78,707
- source bytes: 177,091,176
- retained author records with complete birth/death years: 62,588
- primary samples: 3
- primary values: 203,883
- primary bytes: 565,180
- median primary sample values: 62,588

Run:

```bash
bash datasets/gutendex_catalog_books/download.sh
bash datasets/gutendex_catalog_books/build.sh
bash datasets/gutendex_catalog_books/verify.sh
```

Use `DRY_RUN=1` to inspect the request pattern without fetching. The download
script follows Gutendex `next` links until the catalog is exhausted and writes a
download inventory with page count, row count, source bytes, and observed API
count.
