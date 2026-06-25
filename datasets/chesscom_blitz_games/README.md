# Chess.com Blitz Game Ratings & Lengths (per player)

Numeric Chess.com blitz-game metrics, organized as **one family per quantity** with **one
sample per player's chronological blitz-game stream** — "many player-series of the same
quantity". Supersedes the earlier `chesscom_hikaru_2024_01` draft (one player, one month,
which mixed ratings and a timestamp and fell below the floor).

- Source: https://api.chess.com/pub (Published-Data API, no authentication)
- Local raw payloads: `${DATA_DIR:-.data}/downloads/chesscom_blitz_games/pages/`

## Families & samples

| family | quantity | type |
|---|---|---|
| `chesscom_blitz_rating_u16` | player Elo rating (white & black, game order) | uint16 |
| `chesscom_blitz_plies_u16` | game length in plies (half-moves) | uint16 |

- **A sample** = one player's stream of values for a single quantity, in chronological
  game order (a slowly-drifting Elo series per player).
- **Samples/family** = number of players with `>= CHESSCOM_MIN_RECORDS` non-constant
  values (default 1000).

## Homogeneity

Only **rated, standard (`rules=chess`) blitz** games are kept — one coherent regime. Other
time classes (bullet/rapid/daily) and variants are dropped so a family is a single quantity
on a single scale. Ratings (Elo, ~100–3300) and ply counts (game length, ~1–300) are kept
as **separate families** and never mixed.

## Why per player

Player list is seeded from the live leaderboards (`/pub/leaderboards`), then each player's
recent monthly archives (`/pub/player/{u}/games/archives` → `.../games/{YYYY}/{MM}`) are
crawled. One sample per player gives large, autocorrelated u16 streams that comfortably
clear the adequacy floor.

## Run

```sh
bash datasets/chesscom_blitz_games/download.sh   # ~PLAYERS_MAX x MONTHS_MAX small JSON pulls
bash datasets/chesscom_blitz_games/build.sh
bash datasets/chesscom_blitz_games/verify.sh
```

Tuning env vars: `CHESSCOM_PLAYERS_MAX` (default 50), `CHESSCOM_MONTHS_MAX` (default 24),
`CHESSCOM_SLEEP` (default 0.3s between requests), `CHESSCOM_MIN_RECORDS` (default 1000),
`CHESSCOM_UA` (User-Agent; the API requires a descriptive one). The crawl is resumable:
already-downloaded `pages/<player>__<YYYY>_<MM>.json` files are skipped. Logs under
`${DATA_DIR:-.data}/logs/chesscom_blitz_games/`.
