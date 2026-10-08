# ICON IVM-A Level-2.7 In-Situ Ion Drift Velocity (1 Hz) Float64

Native IEEE-754 float64 **thermal-ion drift velocities** (m/s, relative to
corotation) measured in situ at about 590 km by the Ion Velocity Meter A
(IVM-A) on NASA's Ionospheric Connection Explorer (ICON). The three
geomagnetic components of the drift vector (magnetic zonal, meridional and
field-aligned) are read from the IVM-A Level-2.7 v06 daily NetCDF4 product.
One sample is one component's finite values over one UTC day.

## Source

- Bucket: NASA GSFC HelioCloud, `https://gov-nasa-hdrl-data1.s3.amazonaws.com/spdf/cdaweb/data/icon/l2-7_ivm-a/YYYY/icon_l2-7_ivm-a_YYYYMMDD_v06rNNN.nc`
  (anonymous HTTPS, not requester-pays). The bucket mirrors NASA SPDF/CDAWeb,
  whose GSFC hosts timed out from the authoring environment.
- The prefix holds 1,000 daily IVM-A files (one per day, 2019-11-18 to
  2022-09-01, revisions r000-r003 of version 6, 45.5 GB). IVM-B is a separate
  product under another prefix and is never listed.
- File layout (checked per file): HDF5 superblock v2, root group with 114
  dense links. Each velocity is `float64 (Epoch,)` with normally 86,400
  records (2019-11-22 has 86,404, since days overlap by a few seconds),
  chunked 512 values, filter pipeline shuffle(8) + deflate(6), and a v1 chunk
  B-tree.
- One selected file, 2021-09-03 (3.6 MB), is a partial day: 5,600 records
  (5,054 finite per component) in 510-value chunks. The recipe accepts any
  record count from 1 to 86,500 and reads the chunk length from each
  dataset's layout message. The first download attempt failed on this file
  under the original 86,000-86,500 bound. The file is still one complete
  daily product file, i.e. one natural record.

## Rights

- NASA Science Data license page (<https://science.data.nasa.gov/about/license>,
  re-fetched and checked by `download.sh`): "Unless the data file is marked
  with a restrictive notice or license, data that is provided from a NASA-led
  mission including observations, engineering, calibration, and auxiliary
  data are licensed as Creative Commons Zero. There are no restrictions on the
  usage of these data."
- ICON is a NASA Explorer mission. Each file carries `Project = "NASA > ICON"`,
  and its `Acknowledgement` calls it "the NASA Ionospheric Connection
  Explorer mission".
- In-file `Rules_of_Use = "Public Data for Scientific Use"` (checked per file).
  The ICON Rules of the Road (PDF linked from <https://icon.ssl.berkeley.edu/Data>)
  says: "All data released to the public may be utilized for scientific
  analysis and publication with no restrictions imposed by the ICON mission",
  and asks users to acknowledge the mission and consult the instrument teams.
- Caveat: this recipe reads `Rules_of_Use` as a public-release label, not as a
  "restrictive notice or license" that would displace NASA's CC0 default. A
  stricter reviewer could treat "for Scientific Use" as a use limitation. The
  accepted IRIS recipe from the same bucket relies on the NASA SMD open-data
  policy in the same way.

## Selection

`discover.sh` (S3 ListObjectsV2 metadata only, run 2026-10-08) sorts the
1,000 IVM-A v06 keys by date and takes indexes `floor((2k+1)*1000/240)`,
k = 0..119. That gives **120 days**: 5 in 2019, 44 in 2020, 42 in 2021,
29 in 2022, spread evenly over the mission's data coverage, with revisions
18 r000, 51 r001, 6 r002 and 45 r003. `sources.tsv` pins each key's size,
multipart S3 ETag and LastModified. Its SHA-256
(`5a24feca57bb015b98f221307584568f498a1feffd705b32e8fa7beb9c540893`) is
enforced by `scripts/icon_ivm.py`.

## What is emitted

Series `ivm_a_ion_drift_velocity_f64`, one primary series, with up to
360 samples (120 days x 3 components):

- `ICON_L27_Ion_Velocity_Zonal`: perpendicular to B and the magnetic meridian
  plane, positive east
- `ICON_L27_Ion_Velocity_Meridional`: perpendicular to B in the meridian
  plane, vertical (up) at the magnetic equator
- `ICON_L27_Ion_Velocity_Field_Aligned`: along B

All three are one vector quantity: same unit, instrument (RPA ram component
plus Drift Meter cross-track components), 1 Hz cadence and fit pipeline.
Excluded: ion density and temperature (other units); the instrument-frame
X/Y/Z, raw and original velocities; East/North/Up and equator- or
footpoint-mapped velocities (re-projections of the same measurement, which
would duplicate it); flags; and geolocation.

**Missing values.** `FillVal` is NaN, and NaN records are dropped, so each
sample is the day's finite values in stored record order with no gap markers.
The drop count is recorded per sample (`nan_fill_dropped`), and the three
components share the same NaN mask in every file probed. +-inf is fatal.
Values outside `Valid_Min/Valid_Max` (+-500 m/s) are **kept**
(`outside_valid_range_kept`). `ICON_L27_DM_Flag` / `ICON_L27_RPA_Flag` are
**not applied and not emitted**: they never change the stored values, and
rejecting on them is an analysis choice. As a result, samples include values
the IVM team marks "use with caution" or "should be rejected", typically the
night-side, low-density stretches with the largest excursions. A
(day, component) with fewer than 1,000 finite values would be skipped and
recorded in `filtered/<id>/ingest_stats.json`.

**Index fields.** Beyond the required keys, each row carries `date`,
`component`, `source_variable`, `source_key`, `source_version`, `data_version`,
`source_records`, `nan_fill_dropped`, `outside_valid_range_kept`, `min`/`max`
(computed from the stored float64 values) and `sha256`.

## Scripts

- `download.sh`
  1. Runs the self-test, fetches and checks the NASA license page, and does a
     one-byte liveness GET.
  2. Walks each file's HDF5 metadata by iterating `meta-plan`. Each round,
     every unresolved day names the next 16 KiB block its parser needs, and
     those blocks are fetched in parallel (about 36 blocks per day). This
     includes the creation-order link index that verify uses.
  3. Fetches one contiguous byte span per (day, component), covering its chunks
     (169 x 512 values for a full day; 0.50-0.59 MB, at most 1.10x the stored chunk bytes).
  4. Downloads one complete **control file** (2021-04-07, 45.8 MB, resumable).
  5. Runs `inventory`: inflates and unshuffles every chunk, applies all
     identity and layout checks, requires the control day's cached metadata
     blocks to equal the whole file's bytes and its range decode to be
     byte-identical to a whole-file decode, and records the SHA-256 of every
     span.

  Every range response must report `Content-Range .../<pinned size>` and the
  pinned ETag. Expected transfer is about 0.31 GB.
- `build.sh`: runs the self-test, then decodes from local files only
  (`scripts/icon_ivm.py build`) and repeats the control comparison. It writes
  samples to `samples/<id>/ivm_a_ion_drift_velocity_f64/<year>/icon_ivm_a_<date>_<version>_<component>.bin`,
  plus `index/<id>/samples.jsonl` and `filtered/<id>/ingest_stats.json`.
- `verify.sh`: runs the self-test, then `scripts/verify_samples.py` re-derives
  every sample by separate code paths: the creation-order link index,
  one-shot `zlib.decompress`, byte-plane-zip unshuffle and `struct`-based
  NaN dropping. It byte-compares every sample, recomputes every index field,
  and rejects NaN/inf, constant, short, low-diversity (< 50% distinct) and
  duplicate samples. It also checks that exactly the below-1,000 pairs are
  absent, that all four years are present, the independent whole-file decode
  of the control day, and the manifest totals.
- `discover.sh` regenerates `sources.tsv` (authoring only; not run by the
  download).
- `scripts/h5lite.py`: a pure-stdlib HDF5 reader derived from the accepted
  COSMIC-1 GNSS-RO recipe, with every lookup3 metadata checksum verified.
  Adds a sparse `BlockStore` backend and the shuffle+deflate chunk decode.
- `scripts/selftest.py`: checks lookup3 against the reference vectors, a
  hand-computed unshuffle vector, decode_chunk failure modes and BlockStore
  parity. It also builds a synthetic IVM-A-like HDF5 file end to end (range
  decode vs whole-file decode vs original values, build vs verify decoders,
  NaN policy, MissingBlock) and checks that IVM-B identity, big-endian dtype
  and corrupted headers are rejected.

## Notes

- Novelty: in-situ space-plasma (ionospheric ion drift) velocity has no
  counterpart in the local corpus, registry or downstream mirror per
  `tools/autocollect/novelty.py`. Nearest local families are the HamSCI
  ground-based HF Doppler (f64, different modality) and the DSCOVR solar-wind
  draft (f32, staging). Same host as the accepted IRIS recipe, which uses
  different mission data. This is the second acceptance from this host in the
  current effort.
- Coverage note: the IVM-A L2-7 archive ends 2022-09-01, so the selection
  spans 2019-11-22 to 2022-08-28, not to 2022-11.
