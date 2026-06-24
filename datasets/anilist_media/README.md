# AniList Anime Numerics (per 3-year period)

Numeric anime fields from the AniList GraphQL API, organized as **one family per quantity**
with **one sample per 3-year period** — "many year-series of the same quantity". Supersedes
the earlier recipe, which captured a single 100-item page (below floor).

- Source: https://graphql.anilist.co (AniList API)
- Local raw payloads: `${DATA_DIR:-.data}/downloads/anilist_media/pages/`

## Families & samples

| family | quantity | type |
|---|---|---|
| `anilist_average_score_u8` | average user score (0–100) | uint8 |
| `anilist_popularity_u32` | users with title on a list | uint32 |
| `anilist_favourites_u32` | users who favourited | uint32 |
| `anilist_episodes_u16` | episode count | uint16 *(if dense)* |
| `anilist_duration_u16` | per-episode minutes | uint16 *(if dense)* |

- **A sample** = one 3-year period's values of a single quantity. Periods come from the
  startDate-year shard, grouped into 3-year bins (`ANILIST_BIN_YEARS`).
- **Samples/family** = number of years with `>= ANILIST_MIN_YEAR_RECORDS` non-constant
  values (default 1000); families self-select.

## How it's pulled

The media list is paginated (perPage 50, sorted by id = unbiased), one JSON file per page,
paced to respect AniList's rate limit (~90 req/min) with retry/back-off on 429.

## Run

```sh
bash datasets/anilist_media/download.sh   # paginated GraphQL (~hundreds of paced requests)
bash datasets/anilist_media/build.sh
bash datasets/anilist_media/verify.sh
```

Tuning env vars: `ANILIST_TYPE` (default ANIME), `ANILIST_MAX_PAGES` (default 400),
`ANILIST_SLEEP` (default 0.9s), `ANILIST_MIN_YEAR_RECORDS` (default 1000). Logs under
`${DATA_DIR:-.data}/logs/anilist_media/`.
