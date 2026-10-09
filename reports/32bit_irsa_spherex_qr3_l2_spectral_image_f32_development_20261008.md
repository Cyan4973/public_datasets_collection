# SPHEREx QR3 Level-2 detector-1 calibrated spectral-image float32 development

## Outcome

Accepted `irsa_spherex_qr3_l2_spectral_image_f32`, the first family from the
NASA/IPAC Infrared Science Archive (IRSA). Each sample is the whole IMAGE
extension of one SPHEREx Quick Release 3 (QR3) Level-2 spectral-image exposure
from detector 1. The values are calibrated near-infrared sky surface
brightness in MJy/sr, stored natively as IEEE-754 float32.

The family is distinct from the local astronomy material:
- Raw single-read or up-the-ramp detector DN frames: JWST NIRCam u16, IUE u8,
  IRIS i16, Voyager u8.
- Full-sky HEALPix microwave maps: WMAP f32.
- Catalog columns: Gaia, HYG.
- Interferometer visibilities: EHT.

Downstream `le-u32` has no astronomy images. Novelty kind: `new_source`.

## Source and rights

- **Bucket:** IRSA SPHEREx bucket on AWS Open Data, `s3://nasa-irsa-spherex`
  (us-east-1). Access is anonymous HTTPS and the bucket is not requester-pays.
- **Release:** QR3 Level-2. Primary pipeline runs `l2b-v27-2026-222/223/224/240/241/243`
  only (SSDC pipeline `VERSION = '7.0.5'`); the `l2b_retry` runs are excluded.
- **Pinning:** the bucket is not versioned, so each of the 30 objects is pinned
  in `sources.tsv` by key, ETag, object size, Last-Modified, data offset
  (28,800) and the SHA-256 of its header bytes.
- **Download integrity:** `download.sh` sends Range GETs `bytes=0-16675199`
  with `If-Match` on the pinned ETag, so a reprocessed object fails with HTTP
  412. The SHA-256 of each whole prefix is recorded in `download_plan.tsv` and
  enforced by build and verify.
- **License:** CC0 1.0. The NASA Science Data Licenses page states:
  > Unless the data file is marked with a restrictive notice or license, data
  > that is provided from a NASA-led mission including observations,
  > engineering, calibration, and auxiliary data are licensed as Creative
  > Commons Zero. There are no restrictions on the usage of these data.
- **Mission:** SPHEREx is a NASA MIDEX mission run by JPL/Caltech. The 300
  header cards carry no license or restrictive notice.
- **IRSA terms:** the AWS Open Data registry entry (`spherex-qr`) points to the
  IRSA data-use terms, which say "Most data served by IRSA is public, with no
  usage restrictions". DSS is the only copyrighted exception.
- **Acknowledgement:** IRSA asks for the SPHEREx acknowledgement, which is
  quoted in the manifest citation.

## Shape and conversion

- **Natural record:** one exposure's IMAGE HDU, BITPIX = -32, 2040 x 2040
  (4,161,600 values, 16,646,400 bytes). It holds the zodiacal and diffuse
  background, with a wavelength gradient from the linear variable filter (about
  0.75-1.1 um), plus stars and galaxies, airglow and artifact residue.
- **Prefix fetch:** only the PRIMARY header, the IMAGE header (END card at
  byte 26,320) and the IMAGE data unit are fetched. FLAGS (RICE), VARIANCE,
  ZODI, PSF and WCS-WAVE are never downloaded.
- **Conversion:** a big-endian to little-endian byte swap of the whole data
  unit, with no cropping, scaling, masking or tiling. Every bit pattern is
  kept, including NaN payloads.
- **Missing values:** NaNs are kept and counted in the index. Pixels flagged
  in FLAGS keep their native IMAGE values.
- **Selection:**
  - Three exposures per QR3 week group, from all 10 groups (2026W30_1B ..
    2026W34_2A).
  - Picks fall at observation positions floor((k+0.5)n/3) among about 18,209
    eligible detector-1 exposures.
  - Pointings span RA 17-356 degrees and Dec -75 to +73 degrees; the closest
    pair is 3.3 degrees apart.
- **Regime, enforced in download, build and verify:**
  - DETECTOR=1, BUNIT 'MJy / sr', XPOSURE 113.5826 s.
  - L1DQAFLG=L2DQAFLG=Pass, NON_SURVEY=False, DETCOORD=sky.
  - JACTIVE=KACTIVE=2040.
  - No scaling or compression cards.

## Accepted output

- **Totals:** 30 samples, 124,848,000 float32 values, 499,392,000 bytes.
  Every sample is 4,161,600 values (median 4,161,600).
- **Download:** 30 x 16,675,200 = 500,256,000 bytes of prefixes, plus two
  evidence pages (500,345,425 bytes on disk).
- **Non-finite values:** NaN per image 91-223 (4,060 total); Inf 0.
- **Range:** per-image finite minimum from -6,423.38 to -5,357.25; finite
  maximum from 2,112.94 to 5,458.76.
- **Level:** per-image finite mean from 0.2425 to 1.5051 MJy/sr.
- **Entropy:** 2,715,613 to 3,652,060 distinct bit patterns per image.
- **Breadth (zlsim):** OK. The nearest family is
  `dandi_001076_zebrafish_calcium_fluorescence_f32` at distance 0.0736 (its
  compressor comes within 0.77%). There are no fill warnings.

The figures in the README and manifest for NaNs per image ("~150-200") and
distinct values ("3.1-3.4 M") come from early probes. The realized figures are
the ones above.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py` passed with no warnings.
- **Verify:** I re-ran `bash staging/irsa_spherex_qr3_l2_spectral_image_f32/verify.sh`
  (50 s); it ended `verify_ok samples=30 total_bytes=499392000 groups=10`.
  `build.sh` reads only local files.
- **Bit-exactness:** a separate stdlib struct read of 5,000 random pixels in
  each of 5 samples matched the big-endian source words exactly. END cards sat
  at bytes 400 and 26,320 and data at 28,800 in each file.
- **Distributions:** on 4 samples I checked percentiles, byte-lane entropy
  (8.0, 8.0, 7.1-7.7 and 0.3-1.1 bits), exponent histograms, top values (at
  most 9 repeats) and adjacent-pixel differences. All are consistent with
  calibrated float32 sky brightness and with an honest 32-bit width.
- **Outlier positions:** across all 30 samples, 57 NaN positions and 8-15
  strongly negative positions recur in every image. These are fixed detector
  bad pixels plus transient artifacts, kept native. Nothing is degenerate.
- **Rights:** I read the NASA license page saved by `download.sh`. I fetched
  the AWS registry entry and the IRSA data-use terms page it links. No
  license, restriction or copyright card appears in the header. A grep for
  credentials across scripts and the manifest found none.
- **Novelty:**
  - `novelty.py --url` (S3 prefix and IRSA page) and `--terms` (spherex, irsa,
    linear variable filter, MJy, ipac) match only this candidate.
  - `--type`, `--instrument` and `--archive` each return 0.
  - `--vocabulary` astronomy entries are raw-frame, microwave-map, catalog and
    visibility families.
  - Downstream `le-u32` has no astronomy images.
  - `nasa_fits_sample_image_planes` has sample_count 0.
- **Open risk:** quick-release products may be reprocessed. The ETag
  `If-Match` turns that into a clean HTTP 412, after which `discover.sh` must
  be re-run.
