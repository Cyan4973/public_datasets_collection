# Rick and Morty Character Snapshot

Pinned Rick and Morty API character listing with ids, location ids, and episode counts.

Pinned source: `https://rickandmortyapi.com/api/character?page=1`

Selected series:
- `rickandmorty_character_id`
- `rickandmorty_origin_id`
- `rickandmorty_location_id`
- `rickandmorty_episode_count`
- `rickandmorty_created_unix`

Missing-value policy: Preserves missing origin/location references as sentinel 0 instead of dropping the row.
