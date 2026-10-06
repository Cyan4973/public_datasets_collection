# NOAA/IHO DCDB crowdsourced-bathymetry vessel tracks, LON/LAT float64

Each sample is one **sequential vessel track**. It holds the WGS84
longitude/latitude of every GNSS fix a vessel logged with an echo-sounder
depth sounding, in the order the trusted node wrote them. The stream is
stored as interleaved `LON, LAT` float64 pairs, so consecutive values are
successive positions of one moving (or drifting, or docked) ship, at about
1 s or about 60 s spacing. This is different from the 64-bit coordinate
families already in the corpus:

- `citibike_2024_trip_geocoords_f64`: trip start/end station endpoints, not
  paths.
- `natural_earth_10m_geometry_xy_f64`: cartographic polygon and polyline
  vertices.
- `gbif_occurrence_2024_coordinate_sample`, `geonames_*`, airport and station
  lists: unordered point catalogs.
- `noaa_marinecadastre_ais_2024_01_01_f32`: also vessel positions, but from a
  different source (AIS broadcasts on a 1/10,000-minute lattice) at 32 bits,
  as fields of a report table.

Novelty kind: **new source** within a known modality (geographic
coordinates). It is the first 64-bit sequential geodetic trajectory family in
the corpus, not a new modality. `tools/autocollect/novelty.py` finds no match
for the bucket or for the terms dcdb/bathymetry/crowdsourced in local
recipes, the registry, the ledger, or the downstream mirror.

## Source and license

- Bucket: `https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/` (NOAA Open
  Data Dissemination, IHO Data Centre for Digital Bathymetry hosted by NOAA
  NCEI). Anonymous HTTPS, no credentials, not requester-pays.
- Schema (`docs/readme.html`): every CSV starts with
  `UNIQUE_ID,FILE_UUID,LON,LAT,DEPTH,TIME,PLATFORM_NAME,PROVIDER`. LON and
  LAT are decimal degrees.
- License (`docs/FAQ.html`, last updated Aug 8, 2023; fetched 2026-10-05,
  sha256 `86017f38…2b1a`):

  > Regardless of whether the data are provided to the IHO DCDB by a Trusted
  > Node or an individual, the data is dedicated to the public domain in
  > accordance with the "Creative Commons Zero" universal public domain
  > dedication ( CC0 1.0 ).

  The FAQ also says the DCDB "archives and shares, freely and without
  restrictions, depth data contributed by mariners", and that only data
  from international waters, or from coastal states that agreed to public
  sharing, are published.

## Scope: a documented size cap

S3 prefixes are `csb/csv/<YYYY>/<MM>/<DD>/` by **contribution date**. The
data inside can be older: one kept file starts in 2014. In addition, 148
kept Rosepoint files carry 2004 timestamps, which looks like the GPS
1024-week rollover; TIME is not emitted. The full month of June 2024 is
9,904 objects and 6.06 GB. This recipe takes the seven contribution days
2024-06-01..07: 2,125 objects, 1,583,536,283 bytes (paginated ListObjectsV2
with continuation-token, taken 2026-10-05). After the provider, lattice and
dedup rules below, it downloads **900 objects, 1,172,429,139 bytes**. The
build then excludes 5 of them (see the sub-lattice rule below) and emits
**895 samples, 10,182,222 values, 81,457,776 bytes** from 46 vessels. That is
close to the ~100 MB per-family downstream target. The window is a size cap,
not a quality cut.

## Realized output

| | Value |
|---|---|
| Samples | 895 (Rosepoint 779, GLOS 106, COMIT USF 10) |
| Vessels | 46 (Rosepoint 43, GLOS 2, COMIT USF 1); the largest vessel holds 7.9% of bytes |
| Values / bytes | 10,182,222 float64 / 81,457,776 B |
| Values per sample | min 4, p10 714, median 3,442, p90 38,540, max 261,024 |
| Dropped rows | 0 of 6,815,607 source rows (no empty, non-finite, out-of-range or (0,0) coordinates) |
| Excluded objects | 2 one-row files; 3 coarse 1/60,000-degree files (1,724,494 rows, 298.1 MB of source) |
| Extent | lon -136.39..-66.10, lat 18.43..59.23 (North American coastal and inland waters) |
| Aggregate output SHA-256 | `f17f68579da75162f88b3af234c9be8bdca11cee60a171652f1e63a8fab11c4f` |

Many Rosepoint samples have about 716 values: about 358 one-minute fixes,
which matches 6-hour upload windows. Their contents are distinct tracks
(payload uniqueness is enforced).

## Homogeneity: one decimal lattice

All kept coordinates are printed with at most six fractional digits, with
trailing zeros stripped, so every value lies on the 1e-6 degree lattice.
Discovery read the first 2 KB and last 4 KB of all 2,125 objects (head/tail
range probes):

| Trusted node | Files | Bytes | Per-file max fractional digits | Decision |
|---|---:|---:|---|---|
| Rosepoint | 784 | 1,140,110,755 | 6 in all 784 | keep |
| GLOS | 214 | 54,704,682 | 6 in all 214 | keep 106; drop 108 exact re-uploads |
| COMIT USF | 20 | 10,376,412 | 6 in all 20 | keep 10; drop 10 exact re-uploads |
| PGS | 553 | 103,935,914 | 4 in 229 files, 6 in 324 | exclude: two lattices |
| AquaMap | 324 | 136,795,826 | 14-15 (binary float repr, e.g. `41.037144999999995`) | exclude: off-lattice |
| FarSounder | 230 | 137,612,694 | 6 | exclude: rolling re-submissions (below) |

Fraction-digit counts over all 10.2 M emitted tokens match a 6-digit
lattice with zeros stripped: 6 digits 84.2%, 5 digits 14.2%, 4 digits
1.42%, 3 or fewer 0.16% (`ingest_stats.json`).

FarSounder is on the right lattice but is not independent material in this
window. Its 230 files come from two platforms:

- a ~50-second test track uploaded 58 times;
- one vessel moored near Anacortes, uploaded hourly as rolling windows whose
  time ranges overlap the previous upload (169 overlapping consecutive
  pairs).

Keeping it would add near-duplicate stationary jitter, and partial overlaps
cannot be removed without cutting natural records.

### Effective sub-lattice inside the printed 1e-6 lattice

The full download showed that printed 6-decimal degrees hide the receiver's
real output quantum. A residue test on integer micro-degree magnitudes
n = |value| x 1e6 splits files into clean groups:

- **1/600,000 degree**: NMEA minutes with 4 decimals, rounded to 6 decimal
  degrees. Every n mod 5 is 0, 2 or 3. 605 samples, 85% of bytes.
- **1e-6 degree or finer**: all residues occur. 259 samples (all GLOS and
  COMIT USF files, plus 143 Rosepoint), 15% of bytes.
- **1/60,000 degree**: NMEA minutes with 3 decimals. At least 99.96% of
  distinct n are 0, 17 or 33 mod 50; the exclusion threshold is 90%. 3 Rosepoint files, about 1.85 m resolution, a 10x
  coarser tick. These are excluded, for the same reason as the PGS 1e-4
  files. They are both Nat Geo Quest files, which held 25% of the pre-filter
  bytes in only 2 samples, and one smaller file.

Among files with at least 50 distinct magnitudes, the coarse fraction is
either 0.18 or less, or 0.9996 and above. The 4-decimal-minutes fraction is
either 0.85 or less, or exactly 1.0. So the thresholds (90% coarse to
exclude, all-residues to label as 1/600,000) do not decide any borderline
case. The kept 1/600,000 and 1e-6 classes differ by a factor of 1.67 in
quantum, on the same printed lattice and over the same coordinate domain.
Both are kept, and each sample's class is recorded in the index field
`coordinate_quantum`. Files with fewer than 50 distinct magnitudes (31
small samples) are labeled `unclassified_lt50_distinct` and kept.

The three coarse objects are still in the pinned download: 298.1 MB of the
1.17 GB. The rule needs whole-file content, and the head/tail probes cannot
decide it, so it runs at build time instead of in `selection.tsv`.

### Cadence

Logging cadence varies *within* Rosepoint: some loggers write every ~60 s,
others ~1 s. GLOS and COMIT USF log at 1 Hz. So adding them introduces no new cadence
regime. Unit, datum, lattice and generation process (shipboard GNSS fix per
sounding) are identical across all kept files.

`selection.tsv` lists every object in the window with its size, ETag,
provider, UNIQUE_ID, first/last TIME, and a keep/exclude decision with a
reason. `discover.sh` and `scripts/select_sources.py` regenerate it from the
listing and the probes. Exact re-uploads share UNIQUE_ID, object size and
first/last row TIME/LON/LAT; only the lexicographically first key is kept. A
remaining file that overlaps in time with an earlier kept file of the same
vessel would also be excluded; none occurred.

## Conversion

- One sample per kept CSV object (its natural record: one trusted-node
  submission for one platform). Values are `LON, LAT` interleaved per row in
  file order, little-endian float64, so value_count = 2 x kept rows. Big
  files stay whole: the largest is 176,052,699 source bytes, about 2 M
  values. Tiny files are kept as natural records; 295 samples have fewer
  than 1,000 values.
- Each token is parsed with `float()`, the correctly rounded binary64. For a
  token with at most 6 fractional digits this is exactly `n / 1e6` for
  integer micro-degrees `n`, and it round-trips to the source text. float32
  cannot represent such values (`-124.100532` needs 9 significant digits).
- Missing-value policy, identical in build and verify:
  - Rows are dropped and counted when LON or LAT is empty, unparseable or
    non-finite, out of range, or exactly (0, 0).
  - More than 1% dropped rows overall is fatal.
  - A whole object is excluded and recorded if any kept token is off the
    1e-6 lattice, if it has no valid fix, if all its valid fixes are one
    identical position, or if it sits on the coarse 1/60,000-degree
    sub-lattice.
- Fatal checks:
  - header not exactly the expected string;
  - a row without 8 fields;
  - FILE_UUID differing from the key stem;
  - PROVIDER or UNIQUE_ID changing within a file;
  - duplicate output payloads;
  - time overlap between kept files of one vessel;
  - a changed `selection.tsv` hash or keep totals.
- Not emitted: DEPTH (its precision depends on the provider), TIME,
  UNIQUE_ID, FILE_UUID, PLATFORM_NAME (vessel names) and PROVIDER. The index
  records the public S3 key, ETag, provider and row counts for provenance.

## Scripts

```bash
bash staging/noaa_dcdb_csb_vessel_track_lonlat_f64/download.sh   # 900 objects, 1.17 GB, resumable
bash staging/noaa_dcdb_csb_vessel_track_lonlat_f64/build.sh
bash staging/noaa_dcdb_csb_vessel_track_lonlat_f64/verify.sh
```

- `download.sh` checks the pinned `selection.tsv` SHA-256 and does a
  one-byte liveness GET. It then fetches each kept key with
  `curl -C - --retry 10 --speed-limit 1024 --speed-time 120` (no
  `--max-time`) into a `.part` file. Each object is accepted only after
  its pinned size, S3 composite ETag (MD5 over 5 MiB parts; formula checked
  against S3 for 1-part and multipart objects), exact header and
  first-row FILE_UUID/PROVIDER/UNIQUE_ID match. Per-object SHA-256 values
  go to `downloads/<id>/download_manifest.tsv`.
- `build.sh` (`scripts/csb_tracks.py build`) uses local files only. It
  writes samples, `index/<id>/samples.jsonl` and
  `filtered/<id>/ingest_stats.json`, which holds exclusions, dropped-row
  counts, the fraction-digit histogram, per-provider totals and the
  aggregate SHA-256.
- `verify.sh` (`scripts/verify_csb_tracks.py`) does not import the build
  code. It re-reads every source CSV by byte-level splitting, converts the
  text to integer micro-degrees without floats, and requires every stored
  double to equal `n / 1e6` exactly. It re-derives the quantum class from
  those integers. It also re-derives every index field,
  the exclusion list, payload uniqueness, per-vessel non-overlap, the summary
  and the manifest totals, and rejects degenerate output.

## Caveats

- Rosepoint dominates: 96.2% of bytes and 43 of 46 vessels. The kept
  set is one trusted node's logger population plus two small 1 Hz nodes.
- Tracks include docked and slow-drift periods: GNSS jitter around one
  point, which is real logged material. 175 samples span less than 1e-4
  degree (about 11 m) but hold only 1.1% of bytes. Files whose valid fixes
  are all one identical position are excluded.
- 148 kept Rosepoint files have 2004 timestamps (apparent GPS week
  rollover). TIME is used only for the overlap check; a rollover shifts a
  whole file consistently.
- Exact-duplicate detection runs at selection time, from probe signatures.
  Build and verify then enforce payload uniqueness and per-vessel time
  non-overlap on the full files.
- FarSounder was listed as keepable by the screener but is excluded on
  evidence (rolling overlapping re-uploads). See the homogeneity section.
