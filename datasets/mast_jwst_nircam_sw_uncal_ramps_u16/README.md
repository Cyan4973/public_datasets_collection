# mast_jwst_nircam_sw_uncal_ramps_u16

Raw up-the-ramp readings from the JWST NIRCam short-wavelength (SW) infrared
detectors. Each sample is one whole SCI cube from a Level-1b `*_uncal.fits`
file. It holds 8 non-destructive group reads × 2048 rows × 2048 columns of
native uint16 DN for one H2RG detector during one 837 s exposure: 33,554,432
values, 67,108,864 bytes.

Within a pixel the signal accumulates up the ramp. The cube contains:
- the per-pixel bias/pedestal (about 5,000–11,000 DN)
- dark current, sky and the galaxy-cluster field
- cosmic-ray jumps
- hot and saturated (65535) pixels
- 1/f noise and the 4-pixel reference border

## Source

- MAST public bucket (STScI, AWS Open Data): anonymous HTTPS on
  `https://stpubdata.s3.amazonaws.com/jwst/public/jw02736/jw02736001001/`.
  It is not requester-pays and needs no credentials.
- Program 2736, the JWST Early Release Observations. Observation 1 targets
  the lensing galaxy cluster SMACS J0723.3-7327, observed 2022-06-07. The
  ERO package was released on 2022-07-12 (Pontoppidan et al. 2022, ApJL
  936, L14).
- The files are Level1bModel products from the STScI science data processing
  (SDP). All 12 pinned files carry `SDP_VER = 2026_1b`, and their S3
  Last-Modified is 2026-08-02 (an MAST reprocessing).

## Selection (`discover.sh` + `scripts/discover.py`, pinned in `sources.tsv`)

1. A paginated anonymous S3 ListObjectsV2 of the observation prefix found 84
   SW (`nrca1-4`, `nrcb1-4`) `*_uncal.fits` objects, all 75,556,800 bytes:
   - 30 F090W in visit group 02101
   - 54 F200W in visit group 02105
2. Visit group 02103 is missing. Its SW `uncal.fits` objects are absent from
   the bucket (only previews and cal/rate products are listed), so F150W is
   not represented.
3. A 57,600-byte range probe of every one of the 84 headers showed that all
   84 pass the header regime below. File size alone was never used to infer
   geometry: same-size files in program 2738 use SHALLOW4.
4. Twelve files were pinned:

   | filter | visit group | exposure / detector |
   |---|---|---|
   | F090W | 02101 | 1 NRCA3, 1 NRCB4, 2 NRCA2, 3 NRCA1, 4 NRCB1, 6 NRCA4 |
   | F200W | 02105 | 3 NRCA2, 4 NRCA3, 5 NRCB1, 6 NRCB2, 7 NRCB3, 9 NRCB4 |

   - All eight SW detectors appear.
   - NRCA2, NRCA3, NRCB1 and NRCB4 appear once per filter. The other four
     detectors appear once.
5. Each file is pinned by:
   - S3 key and `versionId` (the download URL is `<key>?versionId=<id>`)
   - size
   - the S3 full-object CRC64-NVME checksum, read with
     `x-amz-checksum-mode: ENABLED` and recomputed locally in pure Python
   - ETag and Last-Modified
   - detector, filter, ACT_ID, exposure, DATE-OBS, TIME-OBS and SDP_VER
6. The `sha256` column of `sources.tsv` was copied from
   `downloads/<id>/download_plan.tsv` after the first full download
   (2026-10-05). Each file matched its pinned size and CRC64-NVME. Download,
   build and verify all enforce the SHA-256.

### Why 12 samples

One natural record is 67.1 MB. The protocol forbids cropping or tiling records,
and caps primary output at 1 GB, which allows at most 14 records. Twelve
records (805,306,368 bytes) give an even 6 + 6 split across the two available
filters and leave headroom under the cap. This is below the ~20-sample
guidance, and the reason is record size: the source itself has 84 eligible
files.

## Homogeneity

All of the following hold for every file and are checked by download, build
and verify.

- **One regime:**
  - one instrument and channel: NIRCam SW, `EXP_TYPE = NRC_IMAGE`,
    `PUPIL = CLEAR`
  - one readout: `SUBARRAY = FULL`, `READPATT = MEDIUM8`, `NGROUPS = 8`,
    `NINTS = 1`, `NFRAMES = FRMDIVSR = 8`, `GROUPGAP = 2`, `NSAMPLES = 1`
  - no on-board compression (`COMPRESS = F`), `DATAPROB = F`,
    `ENG_QUAL = OK`
  - one observation: program 02736, observation 001, visit 001
- **SCI encoding:** `BITPIX = 16`, `BZERO = 32768`, `BSCALE = 1`,
  `BUNIT = DN`, shape (2048, 2048, 8, 1), and no `BLANK`.
- **What varies naturally:**
  - the detector (8 H2RG arrays, each with its own bias pattern and defects)
  - the filter (F090W or F200W, which changes the sky and source level)
  - the dither position
- **Excluded:** long-wave detectors, subarrays, TSO/grism modes, and any
  other readout pattern or group count. SHALLOW4 and MEDIUM8 are never mixed.

## Conversion

1. Walk the FITS 2,880-byte header blocks; offsets are parsed, not
   hard-coded. Observed layout: primary header 17,280 bytes, SCI header
   8,640 bytes, SCI data from byte 25,920. The full HDU chain must be exactly
   PRIMARY, SCI, ZEROFRAME, GROUP, INT_TIMES, ASDF, ending at the file size.
2. Read the 67,108,864-byte SCI data unit (big-endian int16).
3. Add BZERO = 32768 by flipping bit 15 of each big-endian word. This is the
   exact FITS unsigned-16 convention.
4. Write the result as little-endian uint16 in FITS axis order: column
   fastest, then row, then group. Output path:
   `samples/<id>/nircam_sw_full_medium8_uncal_ramp_dn_u16/<file stem>.u16`
5. Nothing is cropped, masked or tiled. Reference pixels, hot pixels,
   saturated 65535 values and the rare 0 DN readings stay (see Realized
   output).
6. ZEROFRAME, GROUP, INT_TIMES and ASDF are not emitted.
7. The pixel order is the JWST DMS science orientation written by the SDP.
   `FASTAXIS` is ±1 depending on the detector, so the original readout
   direction differs between detectors.

Build and verify reject a cube if any of these holds:
- fewer than 1,024 distinct values
- any constant group
- two identical groups
- the interior-row mean of group 8 is not greater than that of group 1 (no
  accumulated signal)
- it duplicates another cube

`verify.sh` uses its own FITS parser, its own CRC64-NVME implementation and a
different decode method (big-integer XOR, then array byteswap). It
byte-compares every sample and recomputes the index min/max/distinct values
from the stored uint16. `scripts/selftest.py` runs first in `build.sh` and
checks both decoders, both HDU walkers and both CRC implementations on a
synthetic FITS file. The synthetic file includes edge values 0, 32767, 32768
and 65535 and a multi-block header.

## Realized output (build of 2026-10-05)

- 12 samples, 402,653,184 uint16 values, 805,306,368 bytes. The aggregate
  sample sha256 is `0a8eb60b…d59ef7`.
- Per-cube values:

  | quantity | per-cube range |
  |---|---|
  | minimum | 0 to 2,387 DN |
  | maximum | 62,062 to 65,535 DN |
  | distinct values | 24,163 to 27,599 |
  | saturated (65535) readings | 0 to 73 |

- The interior-row mean rises 70–130 DN from group 1 to group 8 in every
  cube (bias ≈ 8,500–10,500 DN). Reference-row means move by less than about
  20 DN. This is the expected ramp signature.
- **0 DN readings.** 0 to 46 readings per cube are 0 DN, out of 33.5 million.
  They appear mid-ramp in individual pixels after a large charge deposit, for
  example 9337 → 7000 → 0 → 0 → 0. They are archived values and the SCI
  header declares no BLANK, so they are kept, like every other reading.
- **Same detector, different exposures.** The pairs NRCA2, NRCA3, NRCB1 and
  NRCB4 share the fixed bias pattern: the group-1 median |difference| is
  16–24 DN, against about 1,500 DN between different detectors. Only 1.1–1.7%
  of pixels are exactly equal, so these are not near-duplicates.
- **Entropy.** Generic compressors barely reduce the data: zlib-6 gives 1.13×
  on a whole cube and LZMA gives 1.18× on one group. Exploiting it needs
  modelling of the per-pixel bias and the ramp.

## Rights

The MAST Data Use Policy (`https://archive.stsci.edu/publishing/data-use`)
says:

> "Most data hosted at MAST are in the public domain (see: open data), and
> therefore do not have restrictions on use."

It names three restricted subsets:

| subset | policy wording | applies here? |
|---|---|---|
| exclusive-access data | "may not be retrieved except by authorized and authenticated persons"; afterwards "science data become available for public use without restriction" | No: these files are in `jwst/public/` and are retrieved anonymously |
| HLSPs | CC BY 4.0 | No: these are mission pipeline products, not HLSPs |
| copyrighted collections | the Digitized Sky Survey and the Guide Star Catalogs | No: JWST is neither |

The header has `CATEGORY = 'COM'` because the EROs were executed at the end
of commissioning. They were released publicly in July 2022.

During authoring, `archive.stsci.edu` returned proxy 403 from this
environment, so these quotes were first taken from the copy saved by the
accepted `mast_iue_swp_raw_image_u8` recipe, whose judge verified them. The
driver's run of this recipe's `download.sh` (2026-10-05 19:20) then reached
the page itself. The copy it saved is byte-identical to the IUE copy (81,786
bytes, sha256 `f309e1b4…37e2c3`). Its checks passed:
- the public-domain sentence is present
- the copyrighted list names the DSS and the Guide Star Catalogs and does not
  mention JWST

The fetch remains best-effort:
- a transport failure only logs a warning
- a page that loses the public-domain sentence, or lists JWST as
  copyrighted, is fatal

Acknowledge JWST (NASA/ESA/CSA), NIRCam, MAST and STScI.

## Privacy

The primary header contains the program PI's name (`PI_NAME`). No header text
is written to samples or index rows. The index keeps only these fields:
- file name and URL
- detector, filter, ACT_ID, exposure
- observation date/time, SDP version
- value statistics

## Novelty

`tools/autocollect/novelty.py` found no JWST, STScI-bucket or infrared-ramp
material anywhere: not among local recipes, the registry, the ledger or the
downstream corpus. The nearest local families are single-read raw camera
frames: `nasa_pds_mastcamz_raw_i16` (16-bit) and `mast_iue_swp_raw_image_u8`
(8-bit, same archive, different mission and detector). This family differs
structurally. The group axis holds non-destructive reads of the same pixels,
so a cube contains a per-pixel ramp rather than independent frames.

## Caveats

- **Shared bias patterns.** Two exposures on the same detector share that
  detector's fixed bias pattern and defects. This affects NRCA2, NRCA3,
  NRCB1 and NRCB4, each sampled once per filter. The sky, the sources, the
  cosmic rays and the reset (kTC) noise differ.
- **Single field and day.** All samples come from one target field and one
  observing day. That is a narrow scene scope, but the material is detector
  readout, not scene content.
- **Reprocessing.** MAST reprocesses JWST data. For example, the program 2738
  uncal objects were rewritten on 2026-09-28, and each pinned object currently
  lists only one version. A future reprocessing writes a new object version,
  which can change sizes and checksums and may delete the pinned version. `download.sh` then fails on the version id, CRC64-NVME or
  SHA-256, and `discover.sh` must be re-run to re-pin.
- **Disk use.** The download is 906,681,600 bytes: 12 full files, about 11%
  more than the SCI extensions alone. Full files are fetched so the S3
  checksum and a SHA-256 can pin the whole object.
