# Art Institute of Chicago Artworks Search

Pinned artwork search results with date and artist identifiers.

Pinned source: `https://api.artic.edu/api/v1/artworks/search?q=cat&limit=100&fields=id,date_start,date_end,artist_id,artwork_type_id`

Selected series:
- `artic_artwork_id`
- `artic_date_start`
- `artic_date_end`
- `artic_artwork_type_id`
- `artic_artist_id`

Missing-value policy: Preserves missing artist_id as sentinel 0; otherwise filters out rows missing numeric date fields.
