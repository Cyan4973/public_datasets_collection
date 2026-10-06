# SEVIR storm-event VIL radar-mosaic cubes (uint8)

This recipe collects vertically integrated liquid (VIL) from SEVIR, the Storm
EVent ImageRy dataset (Veillette, Samsi and Mattioli, NeurIPS 2020). SEVIR
VIL is a mosaic of column-integrated liquid water derived from the NOAA NEXRAD
WSR-88D radar network. It is resampled onto a 384 × 384 km Lambert azimuthal
equal-area grid at 1 km per pixel. Each SEVIR event is a 4-hour sequence of 49
frames at nominal 5-minute spacing. STORMEVENTS events are centred on NWS
Storm Events reports such as hail, thunderstorm wind, tornado and flash flood.

One sample is one storm event: the HDF5 slice `vil[i]` of shape
`(384, 384, 49)`. It is stored as uint8 digital-VIL codes, in the file's own C
order, with grid row, grid column, then frame as the innermost axis. Each
sample holds 7,225,344 values (7,225,344 bytes).

## Source and rights

- Bucket: `https://sevir.s3.amazonaws.com/` (`s3://sevir`, us-west-2). It is
  anonymous and supports HTTP `Range` and `If-Match`.
- License: the AWS Open Data registry entry
  (`awslabs/open-data-registry/datasets/sevir.yaml`, ManagedBy Mark S.
  Veillette, MIT Lincoln Laboratory) says *"License: There are no restrictions
  on the use of this data."* `download.sh` re-fetches the YAML and fails if
  that exact line is missing. The bucket has no separate license file.
- Citation: Veillette, M., Samsi, S., Mattioli, C. (2020). *SEVIR: A Storm
  Event Imagery Dataset for Deep Learning Applications in Radar and Satellite
  Meteorology.* NeurIPS 33. The radar data comes from NOAA NEXRAD.

## Encoding of the values (native codes, not converted)

The SEVIR tutorial (`eie-sevir/examples/SEVIR_Tutorial.ipynb`) documents
`vil` as integers 0–254, with 255 marking missing data. Code X maps to kg/m² as
follows:

```
0                         if X <= 5
(X - 2) / 90.66           if 5 < X <= 18
exp((X - 83.9) / 38.9)    if 18 < X <= 254
```

The recipe keeps the stored codes and does not apply this law. Only events
with catalog `pct_missing == 0` are selected, so code 255 must not appear.
download, build and verify all fail if it does. Zeros (no precipitation) are
genuine values and make up most pixels. In the one event probed during
authoring (S789519), about 81% of pixels were 0.

## Selection (bounded subset)

The six STORMEVENTS VIL containers hold 3,910 events in total (about 28 GB),
too much to collect whole. The recipe takes 60 events, 10 from each half-year
container, using a rule fixed in `scripts/select_events.py`. The output is
pinned in `events.tsv`. download/build/verify re-derive it from the catalog,
which is pinned by SHA-256.

1. Rows with `img_type == "vil"` from the six `SEVIR_VIL_STORMEVENTS_*`
   files. RANDOMEVENTS and the ir069/ir107/vis/lght modalities are excluded
   (different sensors, dtypes and regimes).
2. `pct_missing == 0` and `data_max > 0`. This leaves 3,536 of 3,910 events.
3. Per container, rows are sorted by `(time_utc, id)` and only the first event
   of each NWS `episode_id` is kept. No two selected cubes share a storm
   episode.
4. 10 events are taken at evenly spaced positions `floor((k + 0.5) * M / 10)`.

The selection covers June 2017 through September 2019, from the Pacific
Northwest to Florida. Event types include thunderstorm wind, hail, tornado,
flash flood, flood, heavy rain, lightning and funnel cloud. Catalog `data_max`
ranges from 189 to 254. The 2017 H1 container only starts on 2017-06-13
(GOES-16 era), and the 2019 H2 container ends on 2019-09-27. That is the
source's own coverage.

## Acquisition and decode

Whole containers are never downloaded. For each container `download.sh` makes
three kinds of range request:

1. Head bytes `[0, 2048)`. These hold the HDF5 v0 superblock, the root
   symbol-table group (TREE/HEAP/SNOD) and the `vil` object header.
2. Tail bytes `[2048 + N*7,225,344, EOF)`. These hold the `id` object header
   and its fixed 10-byte string data.
3. One exact 7,225,344-byte range per selected event, at
   `2048 + file_index*7,225,344`.

Each request carries `If-Match` with the pinned ETag (`containers.tsv`). The
response must be a 206 with the exact `Content-Range`. `scripts/sevir_hdf5.py`
is a pure-stdlib parser and checks the following:

- the superblock is version 0 and the root group has exactly the links `id`
  and `vil`;
- `vil` has dataspace `(N, 384, 384, 49)`, with N matching the pin and the
  catalog;
- `vil` is unsigned 8-bit fixed-point with layout v3, contiguous at 2048, with
  size `N*7,225,344` and no filter pipeline;
- `id` has shape `(N,)`, and every entry equals the catalog id at that
  `file_index` (all 3,910 rows match).

Because the layout is contiguous and unfiltered, each event range *is* the
decoded uint8 array. build writes it unchanged as one sample.

Each event must also pass these checks:

- max code equals catalog `data_max`;
- min code equals catalog `data_min` (0);
- no 255 codes;
- at least 16 distinct codes;
- not almost entirely zero;
- at least 2 distinct frames.

In the authoring probe of S789519, the catalog `data_max` of 189 matched the
cube exactly.

## Output

- `samples/sevir_vil_storm_events_u8/sevir_vil_storm_event_cube_u8/<sevir_id>.u8`:
  60 files of 7,225,344 bytes each, 433,520,640 bytes in total.
- `index/sevir_vil_storm_events_u8/samples.jsonl`: the required fields plus
  shape, axes, sha256, min/max, source container/index/offset and Storm Events
  metadata (auxiliary only).
- `filtered/sevir_vil_storm_events_u8/ingest_stats.json`: per-event and total
  code histograms.

Downloads come to about 467.5 MB: the 33.8 MB catalog, 433.5 MB of event
ranges and about 64 KB of metadata ranges. The driver's run on 2026-10-05
took 195 s and left 467,544,907 bytes under `.data/*/<id>`.

### Realized output (build of 2026-10-05)

- 60 samples, 433,520,640 uint8 values. Every event has 49 distinct,
  non-empty frames.
- 254 distinct codes in the union. Codes 1 and 255 never occur, and there are
  no missing pixels.
- 48.7% of all values are exactly 0 (VIL below threshold). Codes 1–5 make up
  20.8%; together with code 0 they all decode to 0 kg/m². The linear range
  6–18 makes up 8.8% and the log range 19–254 makes up 21.7%.
- Per-event zero fraction ranges from 0.18 to 0.84 (median 0.48). Distinct
  codes per event range from 133 to 254 (median 254).
- Per-event SHA-256s are pinned in `event_sha256.tsv`. They match the
  SHA-256s in the driver's download log. The SHA-256 of all 60 samples
  concatenated in index order is
  `742700951e156ad4bb24215f0356d9fa4e5f7675cace3242dcd47014ddbec281`.

## Run

```bash
bash staging/sevir_vil_storm_events_u8/download.sh
bash staging/sevir_vil_storm_events_u8/build.sh
bash staging/sevir_vil_storm_events_u8/verify.sh
```

`discover.sh` is optional and metadata-only. It re-lists `data/vil/` and
checks that the six objects still match `containers.tsv`, which shows how the
pins were resolved. `event_sha256.tsv` (`sevir_id`, `sha256`) pins every
event range. It was recorded after the first driver download, and download,
build and verify all enforce it.

## Caveats

- The radar network (NEXRAD) is the same one behind the accepted
  `noaa_nexrad_level3_nids_radials_u8`. The quantity and geometry differ,
  though. That recipe has single-station polar N0Q reflectivity radials. This
  one has a multi-radar, column-integrated VIL mosaic on a Cartesian event grid
  with a time axis.
- The VIL codes are SEVIR's own storage encoding of a derived meteorological
  field (piecewise linear/log). They are kept exactly as the source stores
  them.
- Frame cadence: in the catalog, all 60 selected events have 49 frames at an
  exact 5-minute step. The window is shifted by a few minutes relative to
  `time_utc` for some events (e.g. -118..+122 instead of -120..+120). Frames
  are kept as stored.
