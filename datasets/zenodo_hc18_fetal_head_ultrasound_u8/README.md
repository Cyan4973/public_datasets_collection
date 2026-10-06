# HC18 fetal-head 2D B-mode ultrasound images (uint8)

This recipe collects the images of the HC18 grand challenge
(<https://hc18.grand-challenge.org/>). They are two-dimensional B-mode
ultrasound sonograms of the fetal head in the standard plane used to measure
head circumference. Sonographers at the Department of Obstetrics, Radboud
University Medical Center (Nijmegen) acquired them with GE Voluson E8 and
Voluson 730 scanners during routine screening exams of 551 pregnant women
between May 2014 and May 2015.

One sample is one image: the decoded uint8 grayscale raster at its native size,
written row by row from the top.

| | count |
|---|---:|
| images published (999 training + 335 test) | 1,334 |
| skipped: exact duplicate | 1 |
| skipped: near-duplicate re-exports of the same frame | 8 |
| samples emitted (991 training + 334 test) | 1,325 |
| samples at 800x540 | 1,293 |
| samples at other native sizes (738-800 wide, 539-563 high) | 32 |
| total bytes = total uint8 values | 572,299,207 |

## Source and licence

- Zenodo record 1327317, the latest version of concept record 1322000:
  van den Heuvel TLA, de Bruijn D, de Korte CL, van Ginneken B, *Automated
  measurement of fetal head circumference using 2D ultrasound images*
  [Data set], Zenodo, 2018, doi:10.5281/zenodo.1327317. The challenge page
  cites the first version, doi:10.5281/zenodo.1322001, which has slightly
  different archive sizes and is not used here.
- Paper: van den Heuvel TLA, de Bruijn D, de Korte CL, van Ginneken B,
  *Automated measurement of fetal head circumference using 2D ultrasound
  images*, PLoS ONE 13(8): e0200412 (2018), doi:10.1371/journal.pone.0200412.
- Licence: the Zenodo record metadata declares `"license": {"id": "cc-by-4.0"}`
  with `access_right` `open`. `download.sh` re-checks both on every run. The
  challenge page adds no other terms; it asks users to cite the paper and the
  dataset.
- Ethics: according to the paper, the CMO Arnhem-Nijmegen ethics committee
  approved collection and use of the data. Informed consent was waived because
  collection was retrospective, and all data were anonymized according to the
  Declaration of Helsinki. The manifest marks the material as sensitive
  (clinical) but not personal.

## Files used

| resource | bytes | MD5 | role |
|---|---:|---|---|
| `training_set.zip` | 132,926,838 | `00eb8198b9a505b2b3a6dfc740382497` | 999 image PNGs (944 stored, 55 deflated) plus 999 `*_Annotation.png` masks |
| `test_set.zip` | 43,518,463 | `8402af5d137ef40a2888c1011ef3fe7e` | 335 image PNGs (312 stored, 23 deflated) |
| `training_set_pixel_size_and_HC.csv` | 33,688 | `c0761518fece2bd2d2ad4218f2cd9777` | inventory cross-check, `pixel_size_mm` |
| `test_set_pixel_size.csv` | 9,096 | `8476dc198cc6542f26c57e87faeee033` | inventory cross-check, `pixel_size_mm` |

SHA-256 values recorded from the verified 2026-10-06 download are pinned in
`download.sh` and in the manifest.

The training image names run from `000_HC.png` to `805_HC.png`. There are
also 164 `_2HC`, 23 `_3HC` and 6 `_4HC` images, which are further images from
the same exam, so 806 exams yield 999 training images. The `*_Annotation.png`
files are the sonographers' ellipse masks. They are labels, not measured
material, so they are not decoded. Head-circumference values are labels too
and are not emitted. The pixel size is recorded in each index row as metadata
only.

## Differences from the published description

Decoding the complete archives showed three ways the published description
is inaccurate. Each is handled explicitly and pinned in `scripts/hc18_pins.py`.

1. **Not every image is 800x540.** The challenge page and the paper say every
   image is 800 by 540 pixels. In fact 32 PNGs (24 training, 8 test) have
   slightly different native sizes, from 738x541 to 799x563. They are the same
   material, fetal-head sections exported with a slightly different crop.
   Each exception is pinned by member name and exact size, and every other
   image must be 800x540. They are emitted at their native size, with no
   cropping, padding or resampling, and each index row records its own
   `sample_shape`.
2. **Duplicates.**
   - `training_set/392_2HC.png` is byte-identical to `392_HC.png`: same PNG
     file, same annotation mask, same CSV row. It is skipped.
   - Eight further members are the same acquired frame as an earlier member,
     exported again with 0.35-3.9 % of pixels differing in a small region
     (around the lower-right masking rectangle): training `243_3HC`,
     `788_2HC`, `720_2HC`, `507_2HC`, `198_2HC`, `392_3HC` and `220_2HC`, and
     test `280_HC` (same frame as test `263_HC`). The later member in natural
     order is skipped.
   - Build and verify both re-confirm each skip: the exact duplicate must have
     identical pixels, and each near-duplicate must have the same shape and a
     differing-pixel fraction above 0 and below 10 %. Any other duplicate
     payload is fatal.
   - `scripts/near_duplicate_screen.py` (local-only, not part of build or
     verify) documents how they were found. It runs an all-pairs 24x16
     thumbnail screen over all 1,334 decoded images, then compares candidate
     pairs at full resolution. The closest pairs that were kept (`795_HC` vs
     `795_2HC`, `780_HC` vs `780_2HC`) differ in 64 % and 59 % of pixels: they
     are distinct frames from the same exam. Every other pair among the 1,334
     images has a thumbnail mean absolute difference of at least 4 grey
     levels. The screen output reproduces the pinned list exactly.
3. **Pixel sizes extend beyond the quoted range.** The CSV pixel sizes span
   0.0494-0.3933 mm rather than the quoted 0.052-0.326 mm. They are metadata
   only.

## What a sample contains

The PNGs are kept exactly as published. Every frame includes regions that are
not echo data, and they are kept because they are part of the published
raster:

- black (0) pixels outside the fan-shaped imaging sector (on average 21 % of
  a frame is 0, counting masked and anechoic areas);
- a thin vertical grey-scale bar and a tiny scanner setting label (e.g.
  "Volume / 5.4") at the upper left;
- in most frames, a solid black rectangle at the lower right, presumably
  covering the on-screen measurement readout;
- in a few frames, a bottom scanner status strip (e.g. "Cine 742", "15 sec").

A 64-frame contact sheet and several full-resolution frames were inspected and
showed no patient text. The values are the scanner's display-domain grey
levels after gain, log compression and grey mapping. They span 0-254: the
per-image maximum is 243 for 1,181 of 1,325 images and ranges from 237 to 254
overall. Every frame has at least 204 distinct values, and no value covers
more than 61 % of any frame.

## Conversion

Everything uses the Python standard library only.

1. `download.sh` validates the Zenodo record (id, concept id, title, first
   creator, licence, open access, exact file list with sizes and MD5s). It then
   downloads the four files with resumable curl (`--continue-at -`, stall-based
   `--speed-limit`/`--speed-time`, no hard time limit) and enforces their size,
   MD5 and SHA-256. It also checks each ZIP's end-of-central-directory geometry
   and each CSV's header and row count.
2. `build.sh` first runs `scripts/selftest.py`, then `scripts/hc18_decode.py`:
   - parse each archive's central directory;
   - classify every member (image, annotation, directory; anything else is
     fatal);
   - read each image member through its local header, inflating method-8
     members with `zlib.decompressobj(-15)`, and check size and CRC-32;
   - decode the PNG strictly: IHDR must give the pinned size, bit depth 8,
     colour type 0, non-interlaced; every chunk CRC is checked; PLTE, tRNS and
     unknown critical chunks are rejected; ancillary chunks (only pHYs and tIME
     occur) are skipped; the IDAT stream is inflated and filters 0-4 are
     undone (rows: Paeth 93.5 %, sub 4.4 %, average 1.1 %, none 1.0 %,
     up 0.03 %);
   - confirm and skip the pinned duplicates;
   - write `samples/<id>/hc18_fetal_head_bmode_u8/<split>_<name>.bin`, the
     index `index/<id>/samples.jsonl`, and `filtered/<id>/ingest_stats.json`
     (filter-type and chunk counts, skipped duplicates, value statistics,
     aggregate SHA-256).
3. `verify.sh` re-derives everything independently:
   - it re-checks the MD5s;
   - it reads the archives through `zipfile`, so member CRCs are checked by the
     standard library;
   - it decodes each PNG with a separately written chunk walker and
     flat-buffer unfilter, and byte-compares the result against every sample;
   - it re-confirms the skipped duplicates;
   - it recomputes all index fields and statistics, checks that the sample
     directory matches the index exactly, and checks the floors, the manifest
     `sample_count`/`total_size_bytes`, and the pinned aggregate SHA-256
     (`ffd5dceb156129b58f990d5e8a8dd19d7ed034c7021e57d0b9bd8c3dc5171602`).

The same degeneracy rules are fatal in build and verify: a constant frame,
fewer than 64 distinct values, a modal value covering more than 90 % of the
frame, or an unpinned duplicate frame. The self-test round-trips 141 synthetic
PNGs through both decoders: every filter type, fixed per image and mixed per
row, split IDAT, ancillary chunks, and one full-size 800x540 frame. It also
checks that 15 kinds of malformed PNG are rejected and that the ZIP reader
handles stored, deflated and directory members.

## Running

```bash
bash staging/zenodo_hc18_fetal_head_ultrasound_u8/download.sh   # ~176.5 MB
bash staging/zenodo_hc18_fetal_head_ultrasound_u8/build.sh      # ~2.5 min
bash staging/zenodo_hc18_fetal_head_ultrasound_u8/verify.sh     # ~4 min
```

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/zenodo_hc18_fetal_head_ultrasound_u8/`.

## Novelty and homogeneity

This is a new modality for the corpus: clinical 2D B-mode (brightness-mode)
ultrasound. The only other ultrasound family is
`zenodo_rat_fus_image_sequence_f32`, which holds float32 functional-ultrasound
power-Doppler intensity sequences from a rat brain, a different quantity and
width. An earlier 8-bit ultrasound attempt, `tcia_breast_lesions_usg_u8`, was
blocked because the source was unreachable.

The material is homogeneous: one hospital, one scanner family, one standard
anatomical plane and one grey-level encoding. The frame size is 800x540 except
for 32 slightly different crops. Image content varies with gestational age
(head size within the frame) and with depth and zoom settings. Training and
test images come from the same acquisition and form one series, distinguished
only by the index field `split`. Repeat images from the same exam (`_kHC`) are
kept when they are distinct frames.
