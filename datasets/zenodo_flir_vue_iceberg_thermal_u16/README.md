# zenodo_flir_vue_iceberg_thermal_u16

In-camera T-linear scene-temperature frames (0.04 K per count) from an
uncooled FLIR Vue Pro R 640 thermal camera (13 mm lens, 7.5-13.5 um) flown on
a DJI Phantom 3. The camera imaged a
drifting iceberg and the surrounding seawater in Dickson Fjord, NE Greenland,
on 20-21 August 2018, during an HDMS Lauge Koch research cruise. Each frame is
a native 640x512 single-channel 16-bit TIFF written by the camera, in which
each pixel is a brightness temperature in units of 0.04 K (kelvin = value x
0.04). The recipe emits each frame's pixel plane unchanged as `uint16`
little-endian, one file per frame, in series `flir_tlinear_temperature_u16`.

- Source: Zenodo record 10641368, <https://doi.org/10.5281/zenodo.10641368>
  (Daniel Carlson, published 2024-02-09).
- License: CC BY 4.0. Evidence: the Zenodo API
  (<https://zenodo.org/api/records/10641368>, fetched 2026-10-08) reports
  `metadata.license = {"id": "cc-by-4.0"}`, and the record page shows
  "Creative Commons Attribution 4.0 International". The description says:
  "Each .zip file contains .tiff images as produced by the camera and stored
  on the SD card."
- Attribution (required): Carlson, D. (2024). *Drone thermal infrared imagery
  of a drifting iceberg in Northeast Greenland in August 2018* [Data set].
  Zenodo. https://doi.org/10.5281/zenodo.10641368
- Output: 360 samples, 117,964,800 values, 235,929,600 bytes (655,360 bytes
  per frame).
- Download: 82,015,205 bytes of byte ranges. Only the selected zip members
  are fetched, never the whole zips.

## Population and selection

The record holds six session zips. Their central directories were read with
tail range requests:

| zip | size (bytes) | .tiff frames | selected |
|---|---:|---:|---:|
| 20180820_035505.zip | 70,929,301 | 295 | 37 |
| 20180820_040000.zip | 77,082,289 | 346 | 44 |
| 20180821_034534.zip | 138,761,841 | 634 | 80 |
| 20180821_092823.zip | 324,409,553 | 798 (+ AVI render) | 100 |
| 20180821_155204.zip | 453,347,875 | 786 (+ 3 AVI renders) | 99 |
| 20180821_160000.zip | 71,072,781 | 311 | excluded |

- `20180821_160000.zip` is excluded. All 311 of its members have the same name
  and CRC32 as members of `20180821_155204.zip`, so it is a byte-identical
  subset. `discover.sh` re-checks this.
- The two 20180820 zips are one flight, split at 04:00:00. They are kept as
  separate sessions, since each one is selected independently.
- Frames come at 1 s intervals, so consecutive frames are near-duplicates.
  Within each session, the recipe keeps frames with index % 8 == 0 in
  filename (capture-time) order. That gives one frame every ~8 s and 360 of
  the 2,859 unique frames.
- `scripts/frames.tsv` pins every frame of the five sessions, including the
  unselected ones (`selected = 0`). Each row gives the zip size, the member's
  local-header offset, the range end (the next member's offset - 1), the
  compressed and uncompressed sizes, and the CRC32.
- `discover.sh` re-derives the table from metadata requests and diffs it
  against the pin. It is optional and not part of the download contract.

## Pipeline

1. `download.sh` sends a range GET for `[local header .. data descriptor]` to
   `https://zenodo.org/records/10641368/files/<session>.zip?download=1`. It
   requires:
   - HTTP 206, and a final Content-Range equal to
     `start-end/<pinned zip size>`;
   - the exact range length;
   - a local header with the expected member name and method 8 (deflate). Its
     CRC and size fields must be 0 or equal to the pinned values (upstream
     wrote the zips on macOS, so it sets the data-descriptor flag and leaves
     crc = 0 and csize = 0 in the local header);
   - a raw inflate (`zlib.decompressobj(-15)`) that ends exactly at the
     compressed size, with the inflated size and CRC32 equal to the
     central-directory values, and a matching data descriptor;
   - a TIFF IFD0 with 640x512, BitsPerSample 16, Compression 1,
     SamplesPerPixel 1, Photometric 1, PlanarConfig 1, SampleFormat 1 if
     present, a single page, Make `FLIR` and a Model starting with
     `Vue Pro R 640`;
   - an XMP packet (tag 700) containing exactly one
     `<Camera:TlinearGain>0.04</Camera:TlinearGain>` and exactly one
     `<Camera:IsNormalized>1</Camera:IsNormalized>`. A missing packet, a
     missing tag, or a different value (for example the 0.4 K low-gain mode, or
     non-linearized output) is fatal.

   Each validated range is stored as `<session>/<frame>.tiff.zipmember`.
   Re-runs skip members that already pass validation.
2. `build.sh` re-inflates every member and parses the IFD with the declared
   byte order (II or MM). It concatenates the StripOffsets/StripByteCounts
   strips (655,360 bytes; this is checked, not assumed to start at offset 8)
   and writes the 327,680 values unchanged as uint16 LE. Each frame must pass
   these semantic gates:
   - at least 32 distinct values (the minimum observed is 56, in three open-sea frames);
   - the modal value covers at most 25% of pixels (rejects uniform or
     saturated frames);
   - max - min of at least 50 steps (2 K);
   - at most 0.1% of pixels at 0 or 65535.

   Duplicate frame content (sha256) is fatal.
3. `verify.sh` re-inflates and re-decodes every source and compares it
   byte-for-byte with the stored sample, including the XMP gain check. It recomputes the statistics from the
   stored files and checks the index fields, uniqueness, the directory
   contents, `tlinear_gain_k_per_count = 0.04` in every index row and in
   `ingest_stats.json`, and the manifest's `sample_count` and
   `total_size_bytes`. The `samples/zenodo_flir_vue_iceberg_thermal_u16/`
   tree must contain only the series directory; `build.sh` removes the whole
   tree before writing.

All scripts run a synthetic self-test first. It covers II and MM TIFFs with
1, 3 and 512 strips, deflated zip members with and without data descriptors
(including the upstream macOS layout), rejection of corrupt or truncated
members, wrong geometry, 8-bit depth, wrong camera model, XMP gain 0.4,
IsNormalized 0, missing or duplicated XMP tags, a missing XMP packet, and the
degenerate-frame gates. All scripts honour `DATA_DIR` and log to
`$DATA_DIR/logs/zenodo_flir_vue_iceberg_thermal_u16/`.

## What the values are

Each pixel is the camera's in-camera T-linear scene (brightness) temperature
in units of 0.04 K: kelvin = value x 0.04, Celsius = value x 0.04 - 273.15.
The camera applies its own radiometric calibration and linearization. The
recipe applies no scaling, no offset, and no emissivity or atmospheric
correction. Two pieces of evidence support this:

- Every one of the 360 selected frames has an XMP packet (TIFF tag 700) that
  declares `<Camera:TlinearGain>0.04</Camera:TlinearGain>` and
  `<Camera:IsNormalized>1</Camera:IsNormalized>`. `decode_tiff` enforces both
  in download, build and verify.
- The uploader's notebook `make_FLIR_vid.ipynb`, in the same Zenodo record,
  converts pixels with `(image_array * 0.04) - 273.15`.

Across the 360 built frames, values run from 6,647 to 8,031, which is about
265.9 to 321.2 K:

- the iceberg is about -6 to 0 C;
- seawater is about 10 to 17 C;
- the ship deck at takeoff reaches about 48 C.

Frames have 56-973 distinct levels (median 280). The modal value covers at
most 12.3% of pixels, and no pixel is 0 or 65535. The per-frame range is 57 to
1,125 steps, i.e. 2.3 to 45 K. The three lowest-contrast frames are open sea
at the end of session 20180821_092823. About half the values are odd, so the
low bit is live. The high byte is nearly constant (0x19-0x1F); that is the
natural narrow band of a 0.04 K lattice over this temperature range.

## Registry note

The registry entry `zenodo_radiometric_thermal_u16` is `blocked`, with the
retry condition "Retry only with an exact permissively licensed archive or
direct source known to contain single-channel native-16-bit thermal frames."
This record meets that condition: it is CC BY 4.0, and every frame decodes as
a single-channel, uncompressed, native 16-bit radiometric (T-linear, 0.04 K)
TIFF. That was
verified from the IFD of probe members across all five sessions.

## Deliberate exclusions

- `20180821_160000.zip`, an exact duplicate subset.
- AVI renders and `__MACOSX` resource forks inside the zips.
- `make_FLIR_vid.ipynb`.
- TIFF metadata: EXIF, XMP, and FLIR maker notes. The XMP T-linear gain is
  checked but not emitted.
- The 7 of every 8 frames that are near-duplicates of the kept frames.
