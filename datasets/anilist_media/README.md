# AniList Media Popularity Snapshot

Pinned AniList GraphQL response for popular anime numeric metadata.

Pinned source: `https://graphql.anilist.co`

Selected series:
- `anilist_media_id`
- `anilist_media_episodes`
- `anilist_media_duration_minutes`
- `anilist_media_popularity`
- `anilist_media_average_score`
- `anilist_media_favourites`

Missing-value policy: Filters out titles with null episode, duration, popularity, score, or favourites fields.
