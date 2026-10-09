# NIH ChestX-ray14 frontal chest radiograph uint8 development

## Outcome

Accepted `nihcc_chestxray14_frontal_radiograph_png_u8` from the official NIH
Clinical Center ChestX-ray14 Box share.

This is the corpus's first 8-bit projection radiograph family. It is distinct
from the accepted `tcia_covid19_ny_sbu_chest_cr_u16`, which collects native
12-bit-in-uint16 Carestream detector values from TCIA. This recipe collects
NIH's published 8-bit display-windowed 1024x1024 radiographs from a different
hospital PACS, a different publisher and a different processing pipeline.

## Source and rights

- Source: NIH CC Box folder `https://nihcc.app.box.com/v/ChestXray-NIHCC`.
  The 12 `images_NNN.tar.gz` tarballs (2.0-4.2 GB each, about 45 GB total)
  are served through the static links in NIH's `batch_download_zips.py`.
- Bounded subset: HTTP Range `0-14,680,063` (14 MiB) of every tarball,
  176,160,768 bytes in total. download.sh requires HTTP 206, the expected
  Content-Disposition filename and the pinned Content-Range total.
- Per-prefix SHA-256 values are pinned in `scripts/nih_pins.py`, for example
  images_001 `02c6040f...61b0` and images_012 `97cde53f...3c3f`.
- License evidence: `FAQ_CHESTXRAY.pdf` (72,223 B, SHA-256
  `674665256e6a14c8ebaa93648f438c2b4ca21205167839559bab3ecc89b6b83a`),
  re-fetched and text-checked on every download. Q04: "The usage of the data
  set is unrestricted. But you should provide the link to our original
  download site, acknowledge the NIH Clinical Center and provide a citation to
  our CVPR 2017 paper."
- Manifest SPDX: `LicenseRef-NIHCC-ChestXray14-unrestricted-attribution`.

The grant is an explicit unrestricted-use statement from a US federal agency.
The official README in the same folder adds only a citation request.
The images are de-identified clinical data, so the manifest sets
`contains_sensitive_data = true` and `contains_personal_data = false`,
following the TCIA chest CR precedent. Labels, bounding boxes, age, sex and
view position are never downloaded.

## Shape and conversion

Each natural record is one PNG member `images/<patient>_<followup>.png`. A
sample is its decoded 1024x1024 uint8 grayscale raster, written row-major from
the top row.

1. Inflate the gzip prefix with `zlib.decompressobj(31)`.
2. Walk the ustar headers, verifying each checksum, and keep only members
   whose data ends inside the prefix. The cut trailing member is dropped.
3. Decode each PNG strictly: CRCs checked, consecutive IDAT required, exact
   zlib stream end, filters 0-4 undone.

The recipe writes the stored values unchanged, with no rescale, window, crop
or resample. Members not exactly 1024x1024, 8-bit, colour type 0 and
non-interlaced are skipped and logged. Two were skipped, both RGBA
(colour type 6): images_003 `00004882_001.png` and images_004
`00006757_000.png`.

## Accepted output

- Whole tar members inside the prefixes: 432 (34-38 per tarball)
- Skipped non-grayscale members: 2
- Primary samples: 430
- Distinct patient indices: 429
- Primary values and bytes: 450,887,680
- Sample size: 1,048,576 values (fixed)
- Value range: 0-255
- Distinct values per image: 157-256 (median 254)
- Mean pixel value: 45.2-187.0 (median 119.4)
- Zero fraction: median 0.93 %, mean 2.58 %, max 51.5 % (publisher padding)
- PNG filter rows: none 2,214, sub 1,949, up 31,505, average 187,772,
  Paeth 216,880
- Aggregate SHA-256 over `<sample name>\t<sample sha256>` lines:
  `31787da346e9612163e226e9b736af2f24bc8818c71806200874f34604ef65cd`

The local build and the independent byte-for-byte verification both completed
successfully against the pinned prefixes.

## Judge checks

- `python3 tools/autocollect/gate.py staging/nihcc_chestxray14_frontal_radiograph_png_u8`:
  PASS with no warnings.
- Ran `verify.sh` myself, and it passed. The self-test covers 141 PNG round
  trips, 15 negative cases and 32 tar cuts. The independent re-derivation of
  all 430 samples matched byte for byte, along with the skip list, the patient
  count and the aggregate hash. `build.sh` and `verify.sh` make no network
  calls.
- Download log: all 12 prefixes report `pinned=yes`, and each prefix
  validation names the cut trailing member.
- Bytes, inspected with `struct.unpack` on 10 samples across tarballs:
  - No histogram gaps in 9 of 10. One has 24 gaps from NIH's contrast
    stretch.
  - Order-0 entropy 6.7-7.8 bits; neighbour-delta entropy 2.7-3.8 bits.
  - Pooled zero share 2.47 %.
- Visual review: 1/8-scale thumbnails of 16 samples (including the 5 most
  padded) and half-scale top crops of 6.
  - All are real, upright frontal chest radiographs, so the unfilter and row
    order are correct.
  - The heavy zero fractions are pediatric or rotated films on NIH's black
    canvas, not fill.
  - Burned-in content is limited to technologist L/PORTABLE/initial markers
    plus one NIH redaction box. No names or dates are visible.
- Rights: extracted the FAQ Q04 text myself from the pinned PDF. Fetched
  `README_CHESTXRAY.pdf` (848,327 B) from the same folder; it has no
  restrictive clause.
- Novelty:
  - `novelty.py --url` (Box folder, static host): no other recipe matches.
  - Term searches (chestxray14, radiograph, nihcc, cxr, chestmnist, medmnist,
    chexpert, padchest) hit only the 16-bit TCIA chest CR and unrelated
    families.
  - `--type projection_radiograph` returns only two 16-bit TCIA recipes.
  - A manual listing of downstream `transformer/source_data/8` shows no
    radiograph family.
  - zlsim verdict OK: nearest is downstream `video_luma_y_u8` at 0.068.
- Remaining risk: the recipe depends on NIH's Box static links staying
  available. download.sh fails loudly if sizes, filenames or hashes drift.
