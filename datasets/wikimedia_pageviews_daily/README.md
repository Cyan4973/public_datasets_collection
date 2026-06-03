`wikimedia_pageviews_daily` emits daily Wikimedia pageview count streams for a fixed set of public pages.

Scope:
- fixed 2024 daily window
- fixed public page set across multiple Wikipedia language editions
- source is the Wikimedia REST pageviews API

Series:
- `wikimedia_daily_pageviews`

Transform:
- download one JSON payload per pinned `(project, article)` pair
- keep `items[].views` in API order
- validate the daily timestamp sequence for 2024
- write one raw `uint32` sample per page

Files:
- `download.sh` fetches the pinned JSON payloads into `${DATA_DIR:-.data}/downloads/wikimedia_pageviews_daily/`
- `build.sh` validates payload structure and emits raw little-endian `uint32` samples
- `verify.sh` checks the raw inventory, sample sizes, and `samples.jsonl`
