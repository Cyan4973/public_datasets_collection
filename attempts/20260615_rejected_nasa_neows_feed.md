# Rejected: nasa_neows_feed

Date: 2026-06-15

Reason: the accepted recipe was a single NASA NeoWs 7-day feed snapshot with only
`270` primary values and a median sample size of `45` values. A credible repair
requires widening to many feed windows, but the public `DEMO_KEY` path failed on
the first request with HTTP `403`. Requiring a user-owned `NASA_API_KEY` would
make the recipe credential-gated and not reproducible as a public dataset
acquisition recipe.

Decision: remove the recipe instead of keeping either the tiny original snapshot
or a repaired version that depends on private credentials.

Observed failure:
- command run by user: `./datasets/nasa_neows_feed/download.sh`
- log: `.data/logs/nasa_neows_feed/download.latest.log`
- status: HTTP `403` on `2024-01-01..2024-01-07`

