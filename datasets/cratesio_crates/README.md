# crates.io Crates Search

Pinned crates.io search response with download and version metrics.

Pinned source: `https://crates.io/api/v1/crates?page=1&per_page=100&q=data`

Selected series:
- `cratesio_downloads`
- `cratesio_recent_downloads`
- `cratesio_num_versions`
- `cratesio_created_year`

Missing-value policy: Filters out crates missing download counters or created_at.
