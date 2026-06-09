# Scryfall Default Cards

Pinned Scryfall card search response over paper cards.

Selected series:
- `scryfall_cmc_f32`
- `scryfall_edhrec_rank_u32`
- `scryfall_released_year_u16`
- `scryfall_released_month_u8`
- `scryfall_games_count_u8`
- `scryfall_color_count_u8`
- `scryfall_color_identity_count_u8`

Missing-value policy: preserves zero for missing EDHREC rank and filters rows with invalid release dates or CMC.
