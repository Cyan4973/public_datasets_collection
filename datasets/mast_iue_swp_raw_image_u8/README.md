# mast_iue_swp_raw_image_u8

Raw 8-bit detector frames from the International Ultraviolet Explorer (IUE,
1978-1996) Short-Wavelength Prime (SWP, about 1150-1980 Å) SEC-vidicon camera.
Each sample is one complete 768 × 768 uint8 camera readout. It holds the
low-dispersion spectrum of the target in the large aperture, the camera
background, reseau marks, cosmic-ray hits, and the dark region outside the
circular camera target, all before any NEWSIPS correction.

## Source

- MAST IUE archive: `https://archive.stsci.edu/missions/iue/data/swp/<block>/swpNNNNN.rilo.gz`.
- RILO is the NEWSIPS raw-image product: a gzip-compressed single-HDU FITS
  file with a `BITPIX = 8`, 768 × 768 primary array (MAST file-format page:
  "RILO ... raw image files (a 768x768 byte primary array image)").
- For swp30001, the RILO data unit is byte-identical to the legacy IUESIPS
  VICAR raw image (`swp30001.raw.gz`) after its EBCDIC label. The candidate
  card proposed the VICAR files. RILO was chosen because the VICAR label
  length varies: 21 or 22 records of 360 bytes were observed (597,384 vs
  597,744 bytes decompressed), so a fixed 7,560-byte offset would misalign
  some frames. The FITS header also carries machine-readable homogeneity
  keywords.

## Selection (`discover.py`, pinned in `sources.tsv`)

1. Query the MAST IUE catalogue (`archive.stsci.edu/iue/search.php`, CSV) for
   all 38,130 SWP low-dispersion images.
2. Keep the 16,372 rows that meet all of these:
   - aperture LARGE, station GSFC, image type S (single exposure)
   - raw data present, full read, standard acquisition
   - no trail, multiple or segmented exposure flags
   - exposure > 0
   - object class not 98 (wavelength-calibration lamp) or 99 (nulls/flat
     fields), and no calibration words in the target name
3. Sort by image number, split into 256 equal strata, and take the first
   image per stratum whose RILO FITS header (16 KiB range probe) passes all
   header requirements. 18 candidates were skipped (14 `ABNMINFR = YES`,
   missing minor frames; 4 `ABNHISTR = YES`, history replay).
4. Pins per file: URL, compressed size, ETag, Last-Modified, gzip CRC32, and
   ISIZE (619,200).

Realized scope:
- 256 frames, SWP 506 to 55694, observed 1978-1995 (6-17 per year)
- 59 IUE object classes, 218 distinct target names, 55 thousand-image
  directories
- 85,299,872 compressed bytes

## Homogeneity

The header requirements, checked again by download, build and verify:

- `CAMERA = SWP`, `DISPERSN = DISPTYPE = LOW`, `APERTURE = LARGE`
- `READMODE = FULL`, `READGAIN = LOW`, `EXPOGAIN = MAXIMUM`, `UVC-VOLT = -5.0`
- `STATION = GSFC`
- all `ABN*` abnormality flags `NO`
- `LEXPTRMD = NO-TRAIL`, `LEXPMULT = LEXPSEGM = NO`
- `LIUECLAS` not 98 or 99

Together these fix one camera, one dispersion mode, one aperture, one
gain/voltage setting, and one ground station. What still varies is the
target (stars, AGN, nebulae, planets, comets, sky background) and the
exposure time (about 1.5 s to 25,200 s). Both are natural variation of the
same raw-frame regime.

## Conversion

1. Gunzip, and require that the CRC32 and ISIZE match the pins.
2. Parse the FITS header blocks up to END (28,800 bytes).
3. Copy the next 589,824 bytes unchanged to
   `samples/mast_iue_swp_raw_image_u8/iue_swp_lowdisp_raw_dn_u8/swpNNNNN.u8`.
   These are 768 lines × 768 samples, `NAXIS1` fastest.
4. The 576 FITS padding bytes must be zero.

No masking, scaling, cropping or tiling is applied. Near-zero edge rows,
near-zero edge columns, and saturated 255 DN pixels are genuine and kept.

Build and verify reject a frame if any of these holds:
- fewer than 16 distinct values
- central 256 × 256 mean below 5 DN
- any 64 × 64 corner mean above half the central mean (a misalignment
  guard)
- it duplicates another frame

`verify.sh` re-derives every frame with an independent gzip/FITS parser,
byte-compares it, and checks the index, counts, totals, and the aggregate
DN histogram.

## Rights

The MAST Data Use Policy (`https://archive.stsci.edu/publishing/data-use`)
says: "Most data hosted at MAST are in the public domain ... and therefore do
not have restrictions on use." Its copyrighted collections are only the DSS
and the GSC. `download.sh` re-fetches the page and fails if either statement
changes.

IUE was a NASA/ESA/UK SERC mission. The selection keeps only frames acquired
at the NASA GSFC station.

## Privacy

FITS header label-copy cards include guest-observer surnames and program IDs.
No header text is emitted. `sources.tsv` and the index keep only these
fields:
- image number, file, URL
- size, CRC
- date, exposure
- object class, astronomical target name

## Notes and caveats

- Authoring could only probe headers, so it pinned each file by compressed
  size plus gzip CRC32/ISIZE. After the first full download on 2026-10-05,
  the content SHA-256 of all 256 files was copied from
  `downloads/<id>/download_plan.tsv` into the `sha256` column of
  `sources.tsv`. `download.sh`, `build.sh` and `verify.sh` all enforce it.
- Jupiter pointings (disk, centre, aurora, and Io torus) account for 18 of
  the 256 frames (about 7%). This reflects dense Jupiter campaigns in a few
  strata. Six frames are sky-background exposures (`SKY`, `SKY BKGD`,
  `SKY BACK.`, `BKGD NEAR SATURN`, `URANUS SKYBKG`). These are science
  frames of the same camera regime and were left in.
- Image numbers below about 1000 were reused late in the mission (SWP 506
  was observed in 1990), so image number is not strictly chronological.
