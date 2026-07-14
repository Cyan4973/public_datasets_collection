# StatsBomb Open Match Event Numeric Fields

Collects per-event numeric fields from a bounded, multi-competition set of
[StatsBomb open-data](https://github.com/statsbomb/open-data) association-football
match event streams. The natural record is one match's event stream
(`data/events/<match_id>.json`); each match contributes **one sample per series**,
so collecting many matches yields genuine multi-sample families.

The numeric quantities share one pitch-coordinate and unit system across every
competition (the StatsBomb pitch is a fixed ~120×80 coordinate frame), so mixing
matches from different competitions stays homogeneous.

## Series

Primary (measured quantities, count toward acceptance):

| Series | Type | Meaning |
| --- | --- | --- |
| `statsbomb_event_location_x` | float32 | Event pitch x-coordinate (~0–120) |
| `statsbomb_event_location_y` | float32 | Event pitch y-coordinate (~0–80) |
| `statsbomb_event_duration` | float32 | Event duration in seconds |

Auxiliary (per-event timing, emitted for completeness, **not** counted toward
acceptance per the collection protocol):

| Series | Type | Meaning |
| --- | --- | --- |
| `statsbomb_event_minute` | uint16 | Match minute |
| `statsbomb_event_second` | uint8 | Second within the minute |
| `statsbomb_event_possession` | uint16 | Possession sequence number |

Categorical codes (`type`, `team`, `play_pattern`, `period` ids) are intentionally
**not** emitted — they are low-cardinality enums, not numeric quantities.

## Usage

```bash
datasets/statsbomb_open_events_numeric/download.sh
datasets/statsbomb_open_events_numeric/build.sh
datasets/statsbomb_open_events_numeric/verify.sh
```

Downloads are bounded and resumable. Defaults collect up to 150 matches spread
across competition-seasons; each match event stream is a few MB.

Tunables (all optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `MATCH_LIMIT` | `150` | Total matches to collect |
| `PER_SEASON_LIMIT` | `20` | Matches taken per competition-season |
| `MIN_MATCH_COUNT` | `30` | Minimum usable match files for the download to succeed |
| `MAX_DOWNLOAD_BYTES` | `1000000000` | Aggregate download cap |
| `STATSBOMB_MATCHES_FILE` | — | Newline list of `match_id`s (offline / reproducible selection) |

Only numeric per-event fields are extracted — no player names or identifiers.
