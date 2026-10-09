# DFL Bundesliga Official Optical Position Tracking — Person X / Y / Speed (float32)

Source: Bassek, Rein, Weber, Memmert (2025), *An integrated dataset of
spatiotemporal and event data in elite soccer*, figshare article 28196177 v1,
DOI 10.6084/m9.figshare.28196177.v1, CC BY 4.0 (checked live by `download.sh`
against the figshare API record).

The article contains seven complete matches of German Bundesliga / 2. Bundesliga
official DFL match data. This recipe takes only the seven
`DFL_04_03_positions_raw_observed_*.xml` files (2,622,603,272 bytes in total, pinned by
figshare file id, size and MD5 in `sources.tsv`). It does not fetch the
matchinformation files, which map ids to names, or the event XMLs.

## Material

Each XML is a `PutDataRequest/Positions` document. Every `<FrameSet>` is one
tracked object for one `GameSection` (half) of one match, and holds one `<Frame>`
per 40 ms (25 Hz):

```
<FrameSet GameSection="firstHalf" MatchId="DFL-MAT-J03WOH" TeamId="DFL-CLU-00000P" PersonId="DFL-OBJ-00003X">
<Frame N="10001" T="2022-08-26T16:32:09.760+00:00" X="-0.71" Y="8.63" D="16.71" S="14.39" A="0.00" M="1"/>
```

- `X`, `Y`: pitch-centred coordinates in metres (pitch 105 × 68 m), 0.01 m resolution.
- `S`: speed in **km/h**, 0.01 resolution. Frame-to-frame displacement confirms the unit:
  0.232 m per 40 ms is 20.9 km/h, against `S=20.53`.
- `D`, `A`, `M`, `T`, `N`: not emitted. `D` is a provider distance-rate channel and `A`
  is acceleration, so both are derived. `M` and `T` are bookkeeping fields.

## Series (all primary, float32 little-endian)

| series | field | sample |
|---|---|---|
| `person_x_f32` | `Frame@X` | one person FrameSet (player or referee × half × match) |
| `person_y_f32` | `Frame@Y` | same |
| `person_speed_f32` | `Frame@S` | same |

The `TeamId="BALL"` FrameSets are excluded. They carry Z, BallPossession and
BallStatus, follow different dynamics, and number only 14, so they would make a
thin series of their own. Players (`DFL-CLU-*` team ids) and referees
(`TeamId="referee"`) come from the same tracking system, coordinate frame and
lattice, so they share a series. Substitutes give shorter FrameSets.
`.data/filtered/<id>/build_stats.json` reports the median, min and max length.

Sample files are named `<MatchId>__<GameSection>__<PersonId>.bin` and use only
opaque DFL ids. The index adds `match_id`, `game_section`, `person_id`,
`person_kind`, `team_id`, `frame_first`, `frame_last`, `frame_gaps`, and the
stored-f32 `min` and `max`.

## Realized scope (build of 2026-10-08)

Totals per series:

| | |
|---|---|
| samples | 380 |
| bytes | 90,947,272 |
| values | 22,736,818 |
| all three primary series | 1,140 samples, 272,841,816 bytes |

Coverage:
- 7 matches. 2 are 1. Bundesliga (DFL-COM-000001) and 5 are 2. Bundesliga (DFL-COM-000002).
- 368 player framesets and 12 referee framesets.
- Referee FrameSets appear only in the two 1. Bundesliga files. The 2. Bundesliga files contain no `TeamId="referee"` sets.

FrameSet length in frames (25 Hz):

| | frames | approx. time |
|---|---|---|
| min (late substitute) | 2,352 | about 94 s |
| median | 69,131 | about 46 min |
| max | 78,456 | about 52 min |

No FrameSet has frame-number gaps.

Value ranges, computed from the stored float32 values:

| field | range |
|---|---|
| X | -55.50 to 55.50 m |
| Y | -38.60 to 38.08 m |
| S | 0.00 to 36.30 km/h |

X reaches ±55.50 m in 10,956 frames (0.05%). This looks like the tracking area being clipped 3 m beyond the goal lines. The values are kept as published.

In no sample does a single value cover more than 7.5% of the frames.

## Conversion and policy

- `build.sh` stream-parses each file line by line. Each two-decimal attribute string
  goes through `float()`, then becomes float32 (`array('f')`, little-endian).
- Fatal conditions: a missing or malformed X/Y/S value, non-increasing frame numbers,
  a duplicate (match, section, person) FrameSet, an unknown TeamId kind, or a
  constant sample.
- Frame-number gaps are kept as they are and counted, not filled.
- `verify.sh` re-derives every sample with `xml.etree.ElementTree.iterparse` and
  `struct '<f'`, which is an independent code path, and byte-compares the result.
- `verify.sh` also checks finiteness, non-constancy, stored-f32 min/max, plausibility
  envelopes (|X| ≤ 75 m, |Y| ≤ 55 m, 0 ≤ S ≤ 60 km/h), manifest counts, and floors.

## Download notes

`ndownloader.figshare.com/files/<id>` returns a 302 to a presigned S3 URL that
expires 10 s after it is issued. `download.sh` therefore calls curl in an outer
loop, using `-L -C - --speed-limit 1024 --speed-time 120`. Every attempt re-requests
the ndownloader URL, so each resume gets a fresh signed URL. Each completed
`.part` file is checked before it is renamed:

- size and MD5 against the pins;
- the XML prolog and the `PutDataRequest`, `Positions` and `MatchId` header;
- the closing `</FrameSet></Positions></PutDataRequest>` tail.

## Run

```
bash staging/figshare_dfl_bundesliga_position_tracking_f32/download.sh   # ~2.62 GB
bash staging/figshare_dfl_bundesliga_position_tracking_f32/build.sh
bash staging/figshare_dfl_bundesliga_position_tracking_f32/verify.sh
```
