# NASA IRIS level-1 FUV spectrograph full-readout CCD frames (int16)

40 whole level-1 frames from the far-ultraviolet (FUV) spectrograph of NASA's
Interface Region Imaging Spectrograph (IRIS). Each frame is 1096 slit rows x
4144 wavelength columns of int16 CCD counts (DN). They are decoded from the
RICE_1 tile-compressed FITS files that the NASA GSFC HelioCloud public bucket
serves (`gov-nasa-hdrl-data1`, SDAC IRIS holdings).

- **Material**: dispersed solar far-UV spectra along the 175-arcsec IRIS slit.
  FUV CCD 1 covers about 1332-1358 A (C II 1334/1335 A). FUV CCD 2 covers about
  1381-1407 A (Si IV 1394/1403 A, O IV). The data are level 1: reformatted and
  oriented, but not dark-subtracted, flat-fielded or wavelength-corrected
  (`BUNIT = 'Corrected DN'`).
- **Regime**: one instrument path and one readout setting:
  - FUV, CAMERA 1;
  - CRS 1541, "Full WL coverage, 1x1": both CCDs read in full, no spectral or
    spatial summing;
  - onboard look-up table `LUTID = 0`, meaning no onboard companding: values
    sit on the native unit-DN lattice.

  All frames are `IMG_TYPE = 'LIGHT'` with 15-60 s exposures. They differ in
  exposure time, date, CCD age (the pedestal rises over the years) and solar
  target.
- **Excluded lattice**: frames with `LUTID = 4` were square-root companded on
  board. In a decoded LUTID-4 frame (iris20131012_02490122) the levels step by
  1 DN up to 110 DN, then 2 DN, 9 DN near 400 DN, with only sparse coarse
  levels above about 4,000 DN. That is a different tick lattice, so these
  frames are excluded; they could form a separate family. In the scanned
  pool, 371 unsummed full-readout frames fail only on LUTID = 4, against 207
  that pass the full regime. No LUTID-0 frame from 2013 turned up in the scan.
- **Scope**: 40 frames, one per (date, OBSID) observing run, from 7 science
  OBSIDs over 2014-2022:
  - by year: 2014 2, 2015 3, 2016 3, 2017 6, 2018 6, 2019 6, 2020 5, 2021 5,
    2022 4;
  - by exposure: 30 s (21), 60 s (15), 15 s (4).

  Pointings range from disk centre to the limb: 13 frames lie within 500
  arcsec of disk centre and 17 beyond 850 arcsec.
- **Output**: 40 samples of 4,541,824 int16 values each (9,083,648 bytes),
  363,345,920 bytes in total. The download is 112,109,760 bytes.

## Sample format

`samples/nasa_heliocloud_iris_l1_fuv_frames_i16/iris_fuv_l1_full_readout_dn_i16/<source stem>.i16`

Each sample is raw little-endian int16, row-major in FITS order (column, i.e.
wavelength, varies fastest). Shape is `[1096, 4144]` with axes
`slit_row_y, wavelength_column`.

Missing-value policy: frames are kept whole. Pixels that were not read out
carry the source `BLANK = -32768`:

- rows 1-24 and 1073-1096;
- columns 2049-2096, the gap between the two CCDs;
- columns 4113-4144.

That is 282,752 of 4,541,824 pixels (6.23%) in every realized frame. Readout
rows come from each header's `TSR/TER` and are not hard-coded. Both build and
verify require the BLANK set to equal exactly the complement of the readout
regions, with no BLANK inside them. Every read-out pixel is kept unchanged,
including 0-DN and saturated pixels.

The index (`index/<id>/samples.jsonl`) has the required fields plus:

- source key, path date, `T_OBS`, OBSID, FSN, exposure, CRS, LUTID, pointing
  and readout rows;
- valid/BLANK counts, valid min/median/mean/max and the distinct value count;
- source and sample SHA-256.

`min_value` is -32768 (BLANK is stored).

## Decode

The FITS file has an empty primary HDU, then a BINTABLE `COMPRESSED_DATA` with
1096 `1PB` descriptors (count, heap offset), one per image row:
`ZTILE = 4144 x 1`, `ZCMPTYPE = RICE_1`, `BLOCKSIZE = 32`, `BYTEPIX = 2`, and
no scaling or quantization keywords. Each row tile is Rice-decoded exactly as
CFITSIO `fits_rdecomp_short` does:

- a 2-byte big-endian seed;
- per 32-pixel block, a 4-bit `fs+1` code: `fs < 0` repeats the previous
  pixel, `fs = 14` stores verbatim 16-bit mapped differences, otherwise unary
  quotient plus `fs` low bits;
- zigzag un-mapping and accumulation modulo 2^16, then reinterpretation as
  int16.

Pure standard-library Python. CFITSIO is neither needed nor reachable.

Validation layers:

1. `scripts/selftest.py` runs at the start of `build.sh`:
   - A literal Python port of CFITSIO `fits_rcomp_short` encodes synthetic
     rows that exercise every block code -1..14, BLANK edges, full-range
     wrap-around differences and short last blocks. Both decoders must
     reproduce them and must reject truncated or over-long tiles.
   - A synthetic tile-compressed FITS file with a valid DATASUM/CHECKSUM is
     then decoded end to end.
   - A synthetic square-root-companded frame (levels 100, 102, …, 124, 127,
     129, despite an honest-looking LUTID 0 header) must be rejected by both
     lattice checks.
   - During authoring, the same encoder port also re-compressed 314 sampled
     rows of two real IRIS files byte-for-byte.
2. `download.sh` (via `scripts/check_payload.py`) checks each file against its
   pins:
   - exact size, MD5 (= S3 ETag) and SHA-1 (= `x-amz-checksum-sha1`), which
     are mandatory;
   - SHA-256, frozen into `sources.tsv` after the first download of each file
     and enforced wherever set (build and verify enforce it too);
   - the HDU chain, the header regime including `LUTID = 0`, FITS `DATASUM`
     and the HDU `CHECKSUM`;
   - the pinned header facts, and that the date in the key path matches the
     pin.

   It removes unpinned FITS files left in its own download directory, for
   example from the earlier selection.
3. `scripts/build.py` decodes each file and checks:
   - DATASUM/CHECKSUM, the heap descriptors and the exact BLANK layout;
   - `DATAVALS`, `DATAMIN`, `DATAMAX` and `DATAMEDN` exactly, and `DATAMEAN`
     to within 1e-3;
   - the unit-DN lattice: every integer from `DATAMEDN-5` to `DATAMEDN+15`
     must occur among the valid pixels.

   The pipeline's DATAPnn percentiles are not compared, because they use a
   different rank convention: in the 4 frames checked during authoring they
   sat exactly 1 DN above a floor-rank percentile.
4. `scripts/verify.py` does not import the build code:
   - its own FITS card walker, with `LUTID = 0` required independently;
   - struct-based checksums;
   - a byte-wise line-by-line port of `fits_rdecomp_short`;
   - sort-based statistics and its own lattice check.

   It re-checks MD5/SHA-1 and byte-compares every sample. It also checks the
   index rows, manifest totals, uniqueness, degeneracy (at least 64 distinct
   valid values) and scope (at least 7 OBSIDs and at least 9 years).

Decoding takes about 2 s per frame in each decoder. Build and verify use up to
8 worker processes.

## Selection (`discover.sh`, authoring only)

`download.sh` never crawls the index; it fetches only the 40 keys pinned in
`sources.tsv`. Those keys were resolved on 2026-10-05 as follows:

1. The bucket has 1,439 index CSVs, one per minute of day
   (`indices/iris_iris_data_iris_HHMM.csv`). The scan read every 12th one: 120
   CSVs, about 145 MB of metadata.
2. It kept the 951 level-1 `*_fuv.fits` keys of at least 2,000,000 bytes.
   Unsummed full readouts compress to 2.5-3.1 MB; typical summed or windowed
   FUV files are far smaller.
3. It range-read the first 28,800 bytes of each file (the primary header plus
   the table header). 207 files passed the header regime and another 371
   failed only on LUTID = 4. The other rejects were mostly CRS 1 "FUV full
   frame" single-region readouts, plus windowed, summed and LED frames.
4. Eligibility:
   - a 10-digit science OBSID starting with 3. This drops the 2013
     commissioning OBSIDs 4190004113/4117, OBSID 0, and the 42xxxxxxxx runs.
     The 42xxxxxxxx runs use CRS 1 and fixed calibration-style pointings,
     and the regime already drops them;
   - `QUALITY = SAA = HLZ = 0`;
   - `EXPTIME >= 4 s`;
   - pointing within 1016 arcsec of disk centre;
   - `DATAP99 - DATAMEDN >= 10 DN`.

   That leaves 133 frames, 126 runs and 8 OBSIDs.
5. Ranking: by `DATAP99 - DATAMEDN`, the bright-tail spread above the
   pedestal, to prefer active and limb targets over quiet pedestal frames.
   Diversity limits: one frame per (date, OBSID) run, at most 18 per OBSID
   (45%) and at most 6 per year. The top 40 are taken.
6. Each chosen object was HEADed (with `x-amz-checksum-mode: ENABLED`) to pin
   its size, ETag and full-object SHA-1. 16 frames carried over from the first
   selection keep their frozen SHA-256. The 24 new frames had theirs frozen
   from `download_plan.tsv` after the 2026-10-05 re-selection download. All 40
   rows now carry a SHA-256.

Index `start/stop` timestamps are corrupt (e.g. `0001-03-04`), so dates come
from the key path.

## Rights

The IRIS project's data page (https://iris.lmsal.com/data.html, HTTP 200 on
2026-10-05, 9,810 bytes, sha256 `b0b34efe6c924219...`) states:

> IRIS has an open data policy. When you publish work based on IRIS data,
> please acknowledge IRIS as follows: IRIS is a NASA small explorer mission
> developed and operated by LMSAL with mission operations executed at NASA
> Ames Research Center and major contributions to downlink communications
> funded by ESA and the Norwegian Space Centre.

The NASA basis is the SMD Open Scientific Data Policy, the same as the
accepted `nasa_heasarc_nicer_pi_i16` and `nasa_heasarc_batse_cont_counts_i16`
recipes. Its page was fetched by the driver's download run on 2026-10-05
(`downloads/<id>/evidence/nasa_smd_science_information_policy.html`, 268,037
bytes, sha256 `d1fdc2da6f0da6c9...`) and says:

> NASA holds this information, including publications, data, and software,
> as a public trust to increase knowledge and serve the public good. It is
> Science Mission Directorate (SMD) policy, consistent with NASA and Federal
> policies, that information produced from SMD-funded scientific research
> activities be made publicly available.

Among its principles it lists "Mission data are released as soon as
possible". These are open-data policies, not a named license.

The bucket's `catalog.json` names it "GSFC HelioCloud" / "NASA TOPS ODR
datasets" with a NASA contact, but has no license field and no IRIS entry. No
README or license object exists under `sdac/iris/`. `download.sh` re-fetches
both policy pages best effort. It warns, without failing, on a transport error
or if the phrase "public trust" (SMD) or "open data policy" (IRIS) is missing.

The NASA Images and Media Usage Guidelines, re-read from the copy pinned by
the accepted `nasa_wmap_healpix_sky_maps_f32` recipe, say NASA content
"generally are not subject to copyright in the United States". Their AI
section says NASA is committed to "making data available to everyone", but:

- AI outputs must not be attributed to NASA;
- NASA insignia must not be used with AI imagery or AI training;
- no NASA review or endorsement may be implied.

Acknowledgement: use the IRIS text quoted above, and cite De Pontieu et al.
2014, Sol. Phys. 289, 2733.

## Novelty and caveats

- **Novelty**: new source and new material. `novelty.py` finds no IRIS,
  HelioCloud or solar UV spectrograph material at any width, either locally or
  downstream. The nearest families are:
  - `mast_iue_swp_raw_image_u8`: stellar UV echelle raw images, 8-bit;
  - `nasa_sdo_aia_synoptic_i32`: solar EUV imaging, not dispersed;
  - `mast_jwst_nircam_sw_uncal_ramps_u16`: IR broadband detector ramps;
  - `nasa_pds_cassini_vims_qube_i16`: planetary IR imaging spectrometer.

  IRIS frames are slit spectra: fixed-wavelength emission-line columns
  crossing a spatial axis on a near-constant pedestal. The general modality,
  raw space-detector frames, already has JWST NIRCam accepted at 16 bits in
  this collection effort.
- **Low entropy** (measured on the realized output):
  - in the median frame, 95.6% of read-out pixels lie within +-20 DN of the
    frame median; the range across frames is 78-99.9%;
  - frame medians run from 111 to 163 DN;
  - each frame has 359-1,350 distinct valid values;
  - the 99th percentile sits 11-62 DN above the median (median 23 DN).

  The lattice is dense: 190-201 of the 201 integers from the median to
  median+200 occur in every frame. In the lattice-check window, the
  least-populated value still has 2,196 pixels.
- **Physical check**: in `iris20170504_02010906` the brightest columns are
  the Si IV 1393.8 A line (columns 3098-3109). The local maxima for C II
  1334.5/1335.7 A and Si IV 1393.8/1402.8 A sit 7-9 columns (about 0.1 A)
  from the positions predicted by the approximate level-1 header WCS.
- **Concentration**: two OBSIDs supply 33 of the 40 frames:
  - 3893012099 (18), 30 s full-readout program;
  - 3690015104 (15), 60 s exposures.

  The other five OBSIDs give 1-2 frames each. LUTID-0 full readouts are
  dominated by these programs in the scanned pool.
- **OBSID classes**: the science/calibration split by leading OBSID digit is
  inferred from the data, as described under Selection. It could not be
  checked against IRIS documentation.
- **Not an exhaustive index scan**: the CSV scan is a fixed 120-of-1,439
  minute sample, not the whole index.

## Run

```bash
bash staging/nasa_heliocloud_iris_l1_fuv_frames_i16/download.sh   # ~112 MB
bash staging/nasa_heliocloud_iris_l1_fuv_frames_i16/build.sh
bash staging/nasa_heliocloud_iris_l1_fuv_frames_i16/verify.sh
```

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/nasa_heliocloud_iris_l1_fuv_frames_i16/`.
