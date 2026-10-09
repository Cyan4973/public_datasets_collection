# Google HDR+ Pixel raw Bayer CFA uint16 development

## Outcome

Accepted `google_hdrplus_pixel_raw_bayer_u16`. It collects 29 complete as-captured raw Bayer sensor mosaics from the Google HDR+ burst photography dataset. Each sample is the first input frame (`payload_N000.dng`) of one burst shot on a Google Pixel (`sailfish`) or Pixel XL (`marlin`, or the retail name `Pixel XL`) through the Android Camera2 RAW path.

This is the corpus's first smartphone CMOS raw source and its first 2x2 colour-filter-array lattice. Camera-sensor DN rasters already exist locally: `tumvi_euroc_1024_cam_frames_u16` is monochrome, and `raw_space_frame` covers planetary and astronomical cameras. This family is therefore labelled `new_source`, not a new modality. Measured breadth (zlsim) is OK, with the nearest family `downstream:taxi_do` at distance 0.0763.

## Source and rights

- Source: anonymous public GCS bucket `gs://hdrplusdata`, full release `20171106/bursts/` (3,640 bursts, 28,461 frames, 765 GiB). It is not requester-pays.
- Pinned objects: 29 `payload_N000.dng` files, 219,795,130 bytes. Each file's size, GCS MD5 and generation are pinned in `sources.tsv`.
- License: CC BY-SA 4.0. The bucket README (`https://storage.googleapis.com/hdrplusdata/README.html`) says: "The dataset is released under a Creative Commons license (CC-BY-SA). This license is broad and largely unencumbered, however our main intention is that the dataset be used for scientific purposes." It links the CC BY-SA 4.0 deed. The "scientific purposes" sentence states intent and adds no restriction. Attribution and share-alike apply to the decoded mosaics.
- Citation: Hasinoff et al., *Burst photography for high dynamic range and low-light imaging on mobile cameras*, ACM TOG (SIGGRAPH Asia) 35(6), 2016.
- Privacy: the publisher stripped GPS. The README notes that subjects include the authors' friends and family. The builder screened the 40 evenly spaced candidates by their gallery EXIF thumbnails and excluded 11 bursts showing people; `privacy_screen.tsv` records every verdict. Only CFA pixel values are emitted.

## Selection and homogeneity

`discover.sh` lists every N000 frame through the GCS JSON API and range-reads 4 KiB of each to parse TIFF IFD0. `check_pixel_cfa` keeps 659 frames that match all of the following:

- Make `google`
- Model `sailfish`, `marlin`, `Pixel` or `Pixel XL`
- NewSubFileType 0, Photometric 32803, Compression 7, BitsPerSample 16
- 4048x3036, with 192 tiles of 256x256
- WhiteLevel 1023, BGGR, no LinearizationTable, no SubIFDs

Excluded frames:

| Reason | Frames |
|---|---|
| Legacy uncompressed writer | 1,504 |
| Not Google-made (Nexus or no Make tag) | 1,316 |
| 4048x3044 | 136 |
| 3280x2464 (zoomed or pre-cropped) | 25 |

Sorting the 659 by burst name and taking 40 evenly spaced picks gives the candidate set; the privacy screen leaves 29. Only one frame per burst is kept.

All 29 frames share:

- one sensor and readout geometry
- 10-bit depth
- one BGGR phase
- per-site black levels of 63.0–64.0 DN

## Shape and conversion

Each DNG IFD0 holds 192 lossless-JPEG (ITU-T T.81 SOF3) tiles. Each tile has precision 16, 2 interleaved components x 128 columns x 256 rows, predictor 1, point transform 0, and no restart markers. `scripts/hdrplus_dng.py` is a pure-stdlib decoder supporting Huffman DC tables, predictors 1–7, point transform and restart intervals. The conversion:

1. Decodes each tile and interleaves its two components back into 256-pixel rows.
2. Places tiles row-major and crops the right and bottom edge tiles to 4048x3036.
3. Writes raw little-endian uint16.

There is no black subtraction, linearization, white balance, demosaicing, normalization or rotation. The Orientation tag is recorded in the index: 27 frames are 1 and 2 frames are 6. Sub-black photosites and saturated (1023) photosites keep their native values.

## Accepted output

- Samples: 29 (16 `Pixel XL`, 8 `sailfish`, 5 `marlin`)
- Shape per sample: 3036 rows x 4048 columns = 12,289,728 values (24,579,456 bytes)
- Primary values: 356,402,112
- Primary bytes: 712,804,224
- Download: 219,795,130 bytes
- Global min / max: 0 / 1023. Frame minimums are 61–64 except for 8 frames with isolated sub-black photosites (minimums 0–51). 21 frames reach WhiteLevel.
- Per-frame medians: 67–156 DN
- Aggregate SHA-256 of per-sample hashes: `150d324764ae45f78ab61e3669023e798a5e3c0f7b420c57c76416d8a70a9a2e`

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **verify.sh:** re-run by the judge; PASS for all 29 frames with the aggregate sha above.
- **build.sh:** reads only the local DNGs and `sources.tsv`.
- **Download log:** 29 files, 219,795,130 bytes, matching `sources.tsv`.
- **Independent decode:** I wrote a separate bit-by-bit T.81 decoder that does not import the recipe and compared it with the stored samples on 14 tiles from 5 frames. The tiles cover interior, first-row, right-edge, bottom-edge and corner positions, plus every tile holding a zero-valued pixel. Result: 0 mismatches over 838,000+ values. Every tile's entropy stream ends in 1-bit padding immediately followed by EOI (`FFD9`), so Huffman sync is exact.
- **Byte statistics (stdlib `array`):**
  - Low two bits are uniformly distributed, so the 10-bit precision is genuine.
  - G1 and G2 means agree in every frame.
  - Tile-boundary same-colour gradients equal interior gradients, so there are no seams.
  - Sub-black pixels are isolated: at most 3 per row, spread over many tiles, with normal same-colour neighbours.
  - Several high-gain frames show periodic near-empty codes (on-sensor digital-gain combing), which is native.
  - Mode share is at most 0.168 (black level in a dark frame), so there is no fill issue.
- **Renders:** half- and quarter-resolution demosaiced renders of all 29 stored frames show clean natural-colour scenes that match `privacy_screen.tsv`, which confirms the BGGR phase and correct decoding.
- **Rights:** I fetched the README and confirmed the CC BY-SA statement and the link to the 4.0 deed. The scripts contain no credentials.
- **Novelty:** `novelty.py` found no URL hits for `hdrplusdata` in any layer, and type, instrument and archive queries each return 0. No camera-raw or Bayer family exists downstream at any width.

## Caveats

- Possible incidental figures: in the two church interiors (`0037_20160719_122145_438`, `0127_20161018_111216_343`), half-resolution crops show what may be one small, back-facing person seated in the pews (about 30–60 px at full resolution, not identifiable). The README's statement that "none were seen in the kept set" should be read with this in mind. This does not amount to personal data.
- The residential-street frame shows parked cars; plates may be partly legible at full resolution.
- Scenes skew toward photographer prefixes 0043 (9 frames) and 0155 (7 frames).
- The builder summary calls the privacy screen a "human" screen, but it was done by the agent from 160x120 thumbnails. The judge re-checked it against renders of the actual stored samples.
- The README implies Orientation 6 for all frames; only 2 of 29 carry Orientation 6 (27 are 1). Orientation is not applied in any case.
