# Deezer Chart Tracks

Pinned Deezer chart response with track, artist, and ranking metrics.

Pinned source: `https://api.deezer.com/chart/0/tracks?limit=100`

Selected series:
- `deezer_track_id`
- `deezer_duration_seconds`
- `deezer_rank`
- `deezer_position`
- `deezer_artist_id`
- `deezer_album_id`

Missing-value policy: Filters out rows missing nested artist or album ids.
