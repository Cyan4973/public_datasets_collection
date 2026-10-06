# HC18 fetal-head B-mode ultrasound uint8 development

## Outcome

Accepted `zenodo_hc18_fetal_head_ultrasound_u8`, the complete HC18 grand-challenge image population. Each published 8-bit grayscale PNG is decoded to one native uint8 B-mode ultrasound frame.

This is the first clinical 2D B-mode ultrasound family in the corpus. The only other ultrasound recipe, `zenodo_rat_fus_image_sequence_f32`, holds float32 rat functional-ultrasound power-Doppler tensors. That is a different quantity and a different width. The earlier 8-bit attempt `tcia_breast_lesions_usg_u8` was blocked because its source was unreachable.

## Source and rights

- Source: Zenodo record 1327317, the latest version of concept record 1322000. Title: *Automated measurement of fetal head circumference using 2D ultrasound images*. Authors: van den Heuvel, de Bruijn, de Korte, van Ginneken (Radboud UMC).
- Files:

  | file | bytes | MD5 |
  |---|---:|---|
  | `training_set.zip` | 132,926,838 | `00eb8198b9a505b2b3a6dfc740382497` |
  | `test_set.zip` | 43,518,463 | `8402af5d137ef40a2888c1011ef3fe7e` |
  | `training_set_pixel_size_and_HC.csv` | 33,688 | `c0761518fece2bd2d2ad4218f2cd9777` |
  | `test_set_pixel_size.csv` | 9,096 | `8476dc198cc6542f26c57e87faeee033` |

  SHA-256s are also pinned.
- Licence: CC BY 4.0. The record metadata declares `license.id = cc-by-4.0` with `access_right = open`. `download.sh` re-checks the licence, title, first author, concept id and exact file list on every run.
- The challenge page adds no terms beyond citing van den Heuvel et al., PLoS ONE 13(8):e0200412 (2018), and the dataset DOI. Both citations are in the manifest.
- Safety: de-identified retrospective clinical images. Per the paper, CMO Arnhem-Nijmegen approved the collection, consent was waived, and the data were anonymized. The manifest marks the data sensitive but not personal, as for the accepted TCIA, PhysioNet and OpenNeuro recipes. Only pixels are emitted.

## Shape and conversion

- One sample is one published image: the decoded height × width uint8 raster, written top row first.
- Build reads the ZIP central directory itself, checks local headers and CRC-32, and inflates deflated members.
- The PNG decoder is strict:
  - 8-bit grayscale, non-interlaced, at the pinned size;
  - every chunk CRC is checked;
  - PLTE, tRNS and unknown critical chunks are rejected;
  - IDAT is inflated with an exact end, and filters 0–4 are undone.
- Stored values are written unchanged: no crop, pad, resample or remap.
- Upstream deviations, all pinned in `scripts/hc18_pins.py`:
  - **Sizes:** 32 images (24 training, 8 test) are not 800x540. They range from 738x541 to 799x563 and are emitted at native size.
  - **Exact duplicate:** `training_set/392_2HC.png` duplicates `392_HC.png` and is skipped.
  - **Near-duplicates:** 8 re-exports of an earlier frame differ in 0.35–3.9 % of pixels and are skipped: training 243_3HC, 788_2HC, 720_2HC, 507_2HC, 198_2HC, 392_3HC, 220_2HC, and test 280_HC (a re-export of test 263_HC).
  - Build and verify re-confirm every skip, and any unpinned duplicate is fatal.
- Not emitted: annotation masks and head-circumference labels. Pixel size is index metadata only.

## Accepted output

| | |
|---|---|
| Published images | 1,334 (999 training + 335 test) |
| Skipped | 1 exact + 8 near-duplicates |
| Primary samples | 1,325 (991 training, 334 test) |
| at 800x540 | 1,293 |
| at pinned native sizes | 32 |
| Primary values = bytes | 572,299,207 |
| Minimum sample | 399,258 values |
| Median sample | 432,000 values |
| Maximum sample | 449,837 values |
| Value range | 0–254 |
| Per-image maximum | 243 for 1,181 images |
| Distinct values per frame | ≥ 204 |
| Largest modal fraction | 0.608 |
| Mean zero fraction | 0.210 |
| PNG filter rows | Paeth 668,904 · sub 31,261 · average 8,087 · none 7,115 · up 230 |

Aggregate decoded SHA-256: `ffd5dceb156129b58f990d5e8a8dd19d7ed034c7021e57d0b9bd8c3dc5171602`.

Cosmetic follow-up, not blocking: some script comments still say every image is 800x540 (the `build.sh` header, the `hc18_decode.py` docstring, and the `TOTAL_VALUES` comment in `hc18_pins.py`). The manifest and README are accurate.

## Judge checks

- **Gate:** `gate.py` passes with no warnings: values = bytes = 572,299,207; 1,325 samples; median 432,000; width 8.
- **Verify:** I ran `verify.sh` myself.
  - It exited 0.
  - The selftest passed: 141 round-trips, 15 negative cases, 3 ZIP cases.
  - The independent decode via zipfile and a separate unfilter byte-matched all 1,325 samples and reproduced the pinned aggregate SHA-256.
  - `build.sh` uses only local files. The driver's download log shows matching size, MD5 and SHA-256 for all four files, and the licence re-validated.
- **Bytes:** my own decoder (zipfile plus my own Paeth unfilter) byte-matched 9 members: stored, deflated, odd-size and test-split.
  - Aggregate histogram over 60 random frames: smooth decay from 0, no missing values in 0–254, odd/even ratio 1.01.
  - Neighbour differences are small and there are no repeated rows, as expected for natural speckle images.
  - Rendered frames are correctly oriented B-mode skull sections.
- **Duplicates:** my own all-pairs thumbnail screen of the outputs agrees with the builder's.
  - Closest remaining pairs at full resolution: 795_HC/795_2HC differ in 64 % of pixels, 780_HC/780_2HC in 59 %, and training 701 vs test 088 in 85 % of non-zero pixels. These are distinct frames.
  - The skipped 220_2HC differs from 220_HC only along a removed caliper ellipse and its labels, by 12–19 grey levels. No caliper is visible in either export at 4x zoom. It is the same frame, so the skip is correct.
- **Rights:** I fetched the live Zenodo API record myself: cc-by-4.0, open access, file MD5s identical to the pins. The challenge page states no conflicting terms.
- **Safety:** I inspected contact strips (top and bottom 36 rows of 48 frames) and 4 full frames. They show only scanner graphics (grey bar, setting label, masking rectangle, cine strip); no patient identifiers.
- **Novelty:** checked with `novelty.py` by URL and by terms (head circumference, hc18, ultrasound, sonogram, b-mode, fetal, Voluson). No local, registry or downstream B-mode ultrasound exists, and `transformer/source_data/u8` has no medical imaging.
- **Homogeneity:** one hospital, one scanner family, one anatomical plane, one 8-bit display encoding.
- **Volume:** the complete natural population, under the 1 GB cap, from a 176 MB download.
