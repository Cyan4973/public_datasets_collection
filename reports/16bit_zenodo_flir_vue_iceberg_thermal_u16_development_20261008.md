# FLIR Vue Pro R 640 iceberg thermal-frame uint16 development

## Outcome

Accepted `zenodo_flir_vue_iceberg_thermal_u16` after one repair cycle.

The family holds native 16-bit thermal camera frames written by an uncooled FLIR Vue Pro R 640 (13 mm) microbolometer on a DJI Phantom 3, imaging a drifting iceberg and the surrounding seawater in Dickson Fjord, NE Greenland, on 20–21 August 2018.

Each pixel is the camera's in-camera T-linear scene (brightness) temperature at 0.04 K per count (kelvin = value × 0.04).

The first submission described the values as raw radiometric counts. The repair:
- corrected the unit;
- renamed the series from `flir_raw_counts_u16` to `flir_tlinear_temperature_u16`;
- made the XMP gain and normalization tags mandatory in download, build and verify.

The frame bytes did not change.

This is the first terrestrial or close-range thermal camera family in the corpus. Existing 16-bit thermal material is orbital: `mpc_goes18_abi_cmi_c13_fulldisk_u16` brightness temperature and `mpc_aster_l1t_tir_u16` radiance DN. Novelty is therefore `new_source`, not a new modality.

The recipe also satisfies the retry condition of the blocked `zenodo_radiometric_thermal_u16` entry: a permissively licensed source of single-channel native 16-bit thermal frames.

## Source and rights

- Source: Zenodo record 10641368, Carlson, D. (2024), *Drone thermal infrared imagery of a drifting iceberg in Northeast Greenland in August 2018*, DOI 10.5281/zenodo.10641368 (published 2024-02-09).
- License: CC BY 4.0. Evidence: the Zenodo API reports `metadata.license = {id: cc-by-4.0}` and `access_right = open` for the deposited files.
- The record description states that each zip "contains .tiff images as produced by the camera and stored on the SD card".
- Attribution to Daniel Carlson and the DOI is carried in the manifest and README.
- Resources: five session zips, with sizes and md5 values pinned from the API:

| Zip | Size (bytes) |
|---|---:|
| 20180820_035505 | 70,929,301 |
| 20180820_040000 | 77,082,289 |
| 20180821_034534 | 138,761,841 |
| 20180821_092823 | 324,409,553 |
| 20180821_155204 | 453,347,875 |

- `20180821_160000.zip` is excluded: all 311 of its members are name+CRC32 identical to members of `20180821_155204.zip`.

## Shape and conversion

- Natural record: one camera frame, a 640×512 single-channel uncompressed 16-bit TIFF (BitsPerSample 16, Compression 1, MinIsBlack, II byte order, one 655,360-byte strip). Each is stored as a deflated zip member `<session>/<YYYYMMDD_HHMMSS>.tiff`.
- Download:
  - only `[local header .. data descriptor]` byte ranges of the 360 selected members are fetched (82,015,205 bytes), never the whole zips (1.06 GB including AVI renders);
  - each range must return HTTP 206 with an exact Content-Range whose total equals the pinned zip size;
  - the member is then raw-inflated and checked against the CRC32 and sizes pinned from the central directory in `scripts/frames.tsv` (sha256 `191717da…`).
- Selection: frames with index % 8 == 0 in capture-time order within each session, i.e. one frame every ~8 s, giving 37 + 44 + 80 + 100 + 99 = 360 of 2,859 unique frames. Consecutive 1 Hz frames are near-duplicates.
- Conversion: the IFD0 strips are decoded with the declared byte order and the 327,680 uint16 values are emitted unchanged, row-major, little-endian. There is no scaling, offset, emissivity or atmospheric correction.
- Unit evidence:
  - every frame's XMP (tag 700, plus a second copy trailing the strip) declares `Camera:TlinearGain = 0.04` and `Camera:IsNormalized = 1`;
  - the uploader's notebook `make_FLIR_vid.ipynb` in the same record uses `(image_array * 0.04) - 273.15`.
- `decode_tiff` requires exactly one gain of 0.04 and one IsNormalized of 1 in tag 700; anything else is fatal.
- Per-frame semantic gates:
  - at least 32 distinct values;
  - modal fraction at most 0.25;
  - range at least 50 steps;
  - at most 0.1% of pixels at 0 or 65535.
- Duplicate frame content is fatal.

## Accepted output

- Series: `flir_tlinear_temperature_u16` (primary, native_numeric, uint16 LE)
- Primary samples: 360 (per session 37 / 44 / 80 / 100 / 99)
- Primary values: 117,964,800
- Primary bytes: 235,929,600
- Sample size: 327,680 values (655,360 bytes), with every sample the same size
- Value range: 6,647–8,031 (265.9–321.2 K)
- Distinct values per frame: 56–973, median 280
- Per-frame range: 57–1,125 steps (2.3–45 K)
- Maximum modal fraction: 0.123
- 0 or 65535 pixels: none
- Download: 82,015,205 bytes of member ranges
- Aggregate SHA-256 of frame hashes: `633d823c6749cb58eb93162089734cdcbe9fef63615b9a53c7b389ddf05386f9`
- zlsim breadth: OK. Nearest family is downstream `mitbih_v5_1d_var` at distance 0.0662 (loss 0.0068); there are no fill warnings.

The local build and the independent byte-for-byte verification both completed successfully against the pinned ranges.

Known limits:
- Scene diversity is moderate: one iceberg across five sessions (four flights; the two 20180820 zips are one flight split at 04:00), covering ice, open water, open sea and ship-deck takeoff/landing frames.
- Contrast is low by nature: the high byte stays in 0x19–0x1F.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/zenodo_flir_vue_iceberg_thermal_u16` passes with no warnings.
- **verify.sh:** I ran it myself and it passed in 8.5 s, with the same aggregate as before the repair.
- **Local-only build:** build.sh reads only `.data/downloads/<id>/`.
- **Pins:**
  - frames.tsv sha256 matches the manifest;
  - the download log shows 360 members and 82,015,205 bytes;
  - the zip sizes and md5 values match the Zenodo API, which I fetched myself.
- **Repair items:**
  - a grep for raw count / not temperature / Planck / flir_raw_counts in the recipe finds nothing;
  - the sample tree contains only `flir_tlinear_temperature_u16/` with 360 files;
  - every index row and ingest_stats.json carries `tlinear_gain_k_per_count = 0.04`;
  - the self-test covers rejection of gain 0.4, IsNormalized 0, missing tags, a conflicting duplicate packet and a missing packet.
- **Unit:**
  - with my own stdlib parser (zlib raw-inflate, CRC check, IFD walk), all 360 members carry two XMP copies, both declaring TlinearGain 0.04 and IsNormalized 1 (Pix4D Camera namespace, band LWIR, centre wavelength 10000 nm);
  - I fetched `make_FLIR_vid.ipynb` (md5 `64c32283…`, matching the API) and confirmed `(image_array * 0.04) - 273.15`.
- **Bytes** (16 stored samples across all sessions, using `array('H')`):
  - order-0 entropy 5.9–8.8 bits; delta entropy 2.9–4.5 bits;
  - lag-1 spatial correlation 0.969–0.999;
  - odd-value fraction 0.47–0.59;
  - equal zero-delta rates at even and odd x, so no 2× upsample duplication;
  - all 360 hashes unique; no CRC or name repeats across sessions in frames.tsv;
  - consecutive selected-frame demeaned MAD of 2.1–125 counts (median about 9).
  - The rendered thumbnail grid shows real nadir longwave-infrared scenes: a cold iceberg in warmer water, meltwater streaks, uniform open sea, and deck frames with hands and boots that cannot identify anyone.
- **Novelty:**
  - `novelty.py --url` matches only this staging recipe;
  - term search finds no downstream thermal or FLIR family;
  - `--type thermal_camera_image --instrument flir_vue_pro_r_640_microbolometer` gives 0 matches;
  - the vocabulary lists only orbital 16-bit thermal rasters.
- **Rights:** CC BY 4.0 on the exact deposited zips. There are no credentials in any script and no personal data.
