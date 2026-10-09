# irsa_spherex_qr3_l2_spectral_image_f32

Calibrated near-infrared sky images from NASA's SPHEREx all-sky spectral survey.
Each sample is the whole IMAGE extension of one Level-2 spectral-image file from
detector 1 (SWIR band 1): 2040 × 2040 native float32 surface brightness in
MJy/sr. That is 4,161,600 values, or 16,646,400 bytes, per exposure.

SPHEREx images through a linear variable filter, so the central wavelength
changes across the array (about 0.75–1.1 µm on detector 1). Each image holds:
- the zodiacal-light and diffuse background with its wavelength gradient
  (typical values ~0.2–0.6 MJy/sr; IMAGE is not zodi-subtracted, since the
  zodiacal model sits in a separate ZODI extension)
- stars and galaxies (PSF FWHM ~7.5″ on ~6.2″ pixels)
- He-I airglow
- residue from cosmic rays and artifacts, including strongly negative or
  positive outlier pixels (thousands of MJy/sr) that the pipeline marks in
  FLAGS but leaves in IMAGE

## Source

- IRSA SPHEREx bucket on AWS Open Data:
  `https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/qr3/level2/`. Access
  is anonymous HTTPS, the bucket is not requester-pays, and the us-east-1
  endpoint is used.
- Quick Release 3 (QR3) appeared at IRSA in September 2026. It has ten week
  groups (`2026W30_1B` … `2026W34_2A`), observed 2026-07-20 to 2026-08-23.
  Each group has one primary pipeline run `l2b-v27-<yyyy>-<ddd>` (SSDC
  pipeline `VERSION = 7.0.5`) and sometimes a small `l2b_retry-*` side run,
  which this recipe excludes.
- Layout: `<group>/<run>/<detector>/level2_<group>_<obs>_<exp>D<det>_spx_<run>.fits`.
  Full files are 59–70 MB and hold these HDUs: PRIMARY (empty), IMAGE (float32),
  FLAGS (RICE-compressed), VARIANCE, ZODI, PSF and WCS-WAVE.

## What is downloaded

`download.sh` never fetches whole files. For each pinned object it sends an
HTTP Range GET for `bytes=0-16675199`, which covers:
- the PRIMARY header (2,880 bytes)
- the IMAGE header (25,920 bytes)
- the IMAGE data unit (16,646,400 bytes)

Each local `<stem>.primary_image.fits` is therefore a valid two-HDU FITS file.
Every request carries `If-Match: "<pinned ETag>"`. The bucket is not
versioned, so a reprocessed object answers HTTP 412 rather than returning
mixed bytes. Interrupted transfers resume: the script re-requests the missing
tail and appends it.

Total download: 30 × 16,675,200 = 500,256,000 bytes, plus two small evidence
pages.

## Selection (`discover.sh` → `scripts/discover.py` → `sources.tsv`)

1. Discovery listed all ten week groups and, in each, the detector-1
   directory of the primary run. That gives 1,757–1,845 detector-1 exposures
   per group (18,209 in total) from 609–758 observations per group.
2. In each group the observation numbers are sorted. Three are picked at
   positions ⌊(k+0.5)·n/3⌋, k = 0, 1, 2, preferring exposure number k+1 within
   the observation.
3. Discovery range-probes only the headers of the picked files (≤ 115,200
   bytes each). A pick that fails the header regime advances to the next
   observation. On 2026-10-08 no pick failed, and a second run reproduced
   `sources.tsv` byte-for-byte.
4. The result is 30 exposures, three per week group. Their pointings range
   over RA 17°–356° and Dec −75° to +73°, including fields near both ecliptic
   poles. This spread comes from the survey's scan pattern; it was not
   targeted.
5. `sources.tsv` pins, per file: key, URL, ETag, object size, Last-Modified,
   data offset, prefix length, header SHA-256, week group, pipeline run,
   OBSID, EXPIDN, DATE-OBS, CRVAL1/2, SPS_ELON/ELAT and XPOSURE.
6. `download_plan.tsv` records the SHA-256 of each downloaded prefix, and
   build and verify enforce it.

### Why 30 samples

One natural record is 16.6 MB. Thirty records come to about 500 MB, well
above the ~100 MB per family that downstream sub-samples and half the 1 GB
cap. Three per week group spreads them over the whole release period and
the sky. The source offers about 18k eligible detector-1 exposures, so the
count could be raised later without changing the regime.

## Homogeneity

All of the following hold for every sample, and download, build and verify
check them.
- One detector: directory `1/`, `D1` in the file name, header `DETECTOR = 1`.
  Detectors 2–6 cover other bands with different backgrounds and are
  excluded.
- One release and pipeline: QR3, primary `l2b-v27` runs, `VERSION = 7.0.5`.
- One extension and encoding: IMAGE, `BITPIX = -32`, 2040 × 2040,
  `BUNIT = 'MJy / sr'`, no scaling, no BLANK, not tile-compressed.
- One observing mode: all-sky survey exposures (`NON_SURVEY = False`, about
  113.6 s `XPOSURE`) that passed both the L1 and L2 data-quality assessment
  (`L1DQAFLG = L2DQAFLG = Pass`), with `DETCOORD = sky`.

## Conversion and missing values

- **Conversion:** walk the FITS header blocks to END, take the 16,646,400 data
  bytes, byte-swap every big-endian float32 to little-endian, and write the
  whole image (column fastest, then row) to
  `samples/<id>/spherex_qr3_d1_l2_image_mjysr_f32/<stem>.f32`. There is no
  cropping, scaling or masking, and the conversion is bit-exact.
- **Missing values:**
  - NaN pixels (about 150–200 per image, ~0.004%) are preserved with their
    exact bit patterns, as is any ±Inf.
  - FLAGS is neither fetched nor decoded, so flagged pixels keep their native
    IMAGE values.
  - The index records `nan_count` and `inf_count`. `finite_min`,
    `finite_max` and `finite_mean` are computed from the stored float32 over
    finite values only.
  - An image fails the recipe, rather than being skipped, if any of these
    holds:
    - more than 2% of its values are non-finite
    - it has fewer than 100,000 distinct values, or a constant finite range
    - its mean is outside (−10, 1000) MJy/sr
    - it duplicates another sample
    - any size, ETag, SHA-256 or header-regime check fails

## Verification

`verify.sh` is independent of the build path:
- It parses the headers with its own regex card parser.
- It byte-swaps by slice interleaving, where build uses `array.byteswap`.
- It byte-compares every sample against that re-derivation.
- From the stored float32 it recomputes NaN/Inf counts, finite min/max/mean
  and the number of distinct bit patterns.
- It checks the index fields, the SHA-256 values, the 10 × 3 week-group
  coverage, and the manifest's `sample_count` and `total_size_bytes`.

`scripts/selftest.py` runs from `build.sh`. It checks both header walkers and
both decoders against a struct reference on a synthetic SPHEREx-shaped FITS
file with a multi-block header, HIERARCH cards, escaped quotes, signed zeros,
infinities, payload NaNs, subnormals and float32 extremes.

## License

NASA's Science Data Licenses page
(<https://science.data.nasa.gov/about/license>) says: "Unless the data file
is marked with a restrictive notice or license, data that is provided from a
NASA-led mission including observations, engineering, calibration, and
auxiliary data are licensed as Creative Commons Zero. There are no
restrictions on the usage of these data."
- SPHEREx is a NASA MIDEX mission run by JPL and Caltech.
- The pinned headers carry no license or restrictive notice.
- IRSA asks for this acknowledgement: "This publication makes use of data
  products from the Spectro-Photometer for the History of the Universe, Epoch
  of Reionization and Ices Explorer (SPHEREx), which is a joint project of the
  Jet Propulsion Laboratory and the California Institute of Technology, and
  is funded by the National Aeronautics and Space Administration."
- `download.sh` saves both pages as evidence. A transport failure only logs
  a warning; a fetched page that has lost the quoted text is fatal.

## Caveats

- QR products are preliminary calibrations. IRSA has re-issued earlier QRs:
  QR2 was a reprocessing of QR1, and QR2 headers were later corrected. If an
  object is reprocessed in place, its ETag changes and the download fails
  with HTTP 412. Re-run `discover.sh` and rebuild in that case.
- The data are high-entropy float32: about 3.1–3.4 million distinct bit
  patterns per 4.16 M-pixel image in probes.

## Files

- `discover.sh`, `scripts/discover.py`: resolved `sources.tsv` (metadata-only probes)
- `download.sh`, `scripts/check_payload.py`: range fetch and validation
- `build.sh`, `scripts/build.py`, `scripts/spherex_fits.py`, `scripts/selftest.py`
- `verify.sh`, `scripts/verify.py`
