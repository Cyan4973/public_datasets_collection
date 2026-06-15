# Internet Archive Advanced Search

Accepted recipe for `internetarchive_advancedsearch`.

- Source: https://archive.org/advancedsearch.php
- Local raw payload: `${DATA_DIR:-.data}/downloads/internetarchive_advancedsearch/internetarchive_advancedsearch.json`
- Scope: first 10,000 text-media search rows sorted by identifier.
- Primary series: `ia_downloads`, `ia_item_size_bytes`.
- Repair note: this supersedes the smaller `internet_archive_metadata` one-page recipe.
