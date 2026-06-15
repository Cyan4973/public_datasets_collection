# OpenAlex Works 2024 Sample

Bounded cursor-paginated slice of OpenAlex works whose publication date falls
in calendar year 2024.

The repaired recipe downloads `20,000` works by default using OpenAlex cursor
pagination. The primary payload is a table of native date/count/metric fields
and stable JSON-array cardinalities for each work. It is intentionally bounded
well below the repository's 1 GB output limit while extracting enough numeric
material to avoid a tiny salvage from verbose JSON pages.

The script accepts optional `OPENALEX_MAILTO` for OpenAlex polite-pool requests.
No API key is required.
