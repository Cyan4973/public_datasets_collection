`movielens_latest_small` emits native numeric rating and timestamp streams from the public GroupLens MovieLens latest-small archive.

Scope:
- pinned `ml-latest-small.zip` archive
- all rows from `ratings.csv`

Series:
- `movielens_rating`
- `movielens_rating_timestamp`

Transform:
- download the archive
- read `ratings.csv` in source order
- keep `rating` as float32
- keep `timestamp` as uint32

Missing-value policy:
- malformed rows are fatal
- no synthetic fill is applied
