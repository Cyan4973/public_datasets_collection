# earthscope_4p_mt_magnetic_field_counts_i32

Native int32 fluxgate magnetometer counts from the NSF EarthScope USArray
Magnetotelluric Transportable Array (FDSN network **4P**, DOI
[10.7914/SN/4P_2006](https://doi.org/10.7914/SN/4P_2006), CC BY 4.0).
NIMS long-period MT stations recorded the three magnetic-field components
(`LFN`, `LFE`, `LFZ`) at 1 sample/s with an overall sensitivity of
100.9048 counts/nT during deployments of about three weeks.

## Scope

- 16 station deployments, one per calendar year 2006-2018 plus a second one in
  2012, 2015 and 2016 (Oregon/Idaho in 2006 through Virginia/Pennsylvania in
  2016 to Nebraska in 2018), all three magnetic components each: 48 channel
  epochs, pinned in `selection.tsv`.
- Selection rule (`scripts/mt_mseed.py select`, reproducible from the station
  listings): among 1073 4P epochs where LFN/LFE/LFZ share identical start and
  end, have an empty location code, sensor `NIMS`, scale `100.9048` nT and
  `1.0` sps, take the epoch closest to 21 days per year (tie: station code).
- Excluded: electric channels LQN/LQE (mV/km, different unit), the few
  calibration-variant epochs listed with sensor `NIMS 2611-*` or `LEMI` at
  scale 1e11 counts/T, and every other MT network or logger.
- Realized: 48 epochs -> 135 contiguous segments, 86,447,694 int32 values,
  345,790,776 bytes, from 60,215,296 bytes of Steim2 miniSEED. Three primary
  series, one per field component, each with 45 samples / 115,263,592 bytes.
  Segment sizes: median 777,026 values, max 1,806,904, min 1,509. 36 are short
  startup/restart fragments of 1.5k-3k values before the first logger
  restart. Per-epoch decoded counts and payload sha256 are pinned in
  `selection.tsv`.

## Natural record and samples

One record is one station-channel deployment epoch as listed by
fdsnws-station. Within an epoch, the build splits at data gaps (next record
starts more than 0.5 s away from the predicted time) and writes one sample per
contiguous segment. It never concatenates across gaps or epochs. A -1 s step at a UTC
leap second (2008-12-31, 2012-06-30, 2015-06-30, 2016-12-31) is continuous
1 sps sampling, not an overlap. ALW48 crosses the 2015 leap second. Segments
shorter than 1000 values are dropped and counted in
`filtered/<id>/ingest_stats.json`.

## Content notes (not cleaned)

- Values carry the static main-field offset along each sensor axis. LFN
  (magnetic north) sits around 1.4-3.0e6 counts. LFE (magnetic east) is centred
  near zero, typically within a few times 1e4. LFZ (vertical) sits around
  4.3-6.8e6. Diurnal and storm variation adds a few thousand counts on top.
  All three share the same unit and gain, but because the offsets differ, each
  component is a separate primary series:
  `mt_nims_bfield_{north_lfn,east_lfe,vertical_lfz}_counts_i32`.
- Gaps: 93 gaps over the 48 epochs, the same on all three components of a
  station. Largest: NEN29 (96,265 s) and MTE18 (54,825 s). NVN07 has none. Three
  epochs (ALW48 x3) cross the 2015 leap second. Six 1-value fragments
  (ORI09) were dropped.
- Isolated single-sample spikes (an up-jump and a return of more than 1e5 counts)
  occur about 21 times across 135 segments, almost all on LFN/LFZ and often at a
  segment start (e.g. ALW48 LFZ sample 2 = 5,946,319 against about 4.357e6).
  Startup transients also occur (ALW48 LFN's first fragment dips to 1.995e6).
  These are real logger output, preserved and not removed.

## Pipeline

- `download.sh`: runs the decoder self-test, fetches the three station
  listings, checks every pinned epoch is still listed with the standard gain
  (`check-station`), then one fdsnws-dataselect request per epoch
  (`nodata=404`). Each payload is fully decoded (`inspect`) before it is
  accepted. `selection.tsv` pins `expected_values` and `mseed_sha256` for
  all 48 epochs, and both are enforced. Payloads are small (about 1.3 MB), so failed transfers are
  refetched whole.
- `build.sh`: local files only. Steim2 decode, gap split, int32 LE output under
  `samples/<id>/<series_id>/` (one directory per component), plus `index/<id>/samples.jsonl` with
  per-sample station, channel, epoch, segment start, coordinates, source sha256,
  min/max, distinct count and dominant-value fraction.
- `verify.sh`: re-decodes every source file, compares bytes and index fields,
  re-reads the stored int32 words, rejects segments with fewer than 2 distinct
  values or a single value above 50 % of the segment, checks that the directory
  matches the index exactly, and checks manifest totals.

## Decoder

`scripts/mt_mseed.py` is pure standard-library Python. Steim2 handles all
seven difference packings (4x8, 1x30, 2x15, 3x10, 5x6, 6x5, 7x4 bits) and
checks the reverse-integration constant on every record. The `selftest`
subcommand encodes synthetic records that use every packing, 30-bit jumps,
a negative X0 and a gap. It checks round-trip equality, segmentation, the
leap-second and overlap rules, and that corruption and foreign streams are
rejected. On real data, ALW48 LFN decodes to 1,808,194 values, which is
1,809,875 nominal - 1,682 s of gaps + 1 leap second.
