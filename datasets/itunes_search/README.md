# iTunes Search Song Metrics

Pinned iTunes Search response for a song search with pricing and duration fields.

Pinned source: `https://itunes.apple.com/search?term=data+science&entity=song&limit=100`

Selected series:
- `itunes_artist_id`
- `itunes_collection_id`
- `itunes_track_id`
- `itunes_track_time_ms`
- `itunes_track_price`
- `itunes_collection_price`
- `itunes_release_year`

Missing-value policy: Filters out rows missing price or duration fields.
