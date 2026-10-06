# JWST NIRCam short-wave uncal up-the-ramp uint16 development

## Outcome

Accepted `mast_jwst_nircam_sw_uncal_ramps_u16`. Each sample is the whole SCI cube of one JWST NIRCam short-wavelength (SW) detector exposure, decoded from the MAST Level-1b `*_uncal.fits` product. A cube holds 8 non-destructive group reads of a 2048 × 2048 HgCdTe H2RG array in raw uint16 DN.

This is the first JWST, near-infrared, up-the-ramp material in the corpus at any width. Unlike single-read camera frames (`nasa_pds_mastcamz_raw_i16`, `mast_iue_swp_raw_image_u8`), the group axis holds repeated reads of the same pixels. Each pixel therefore carries its bias pedestal, an accumulating ramp, cosmic-ray jumps, and 1/f and reference-pixel structure.

## Source and rights

- **Source:** MAST public bucket `stpubdata` (STScI, AWS Open Data), anonymous HTTPS, not requester-pays, prefix `jwst/public/jw02736/jw02736001001/`.
  - Program 2736 is the JWST Early Release Observations. Observation 1 targets SMACS J0723.3-7327, observed 2022-06-07; the ERO package was released 2022-07-12.
- **Files:** 12 objects of 75,556,800 bytes each (906,681,600 bytes in total), all `SDP_VER = 2026_1b`, S3 Last-Modified 2026-08-02.
- **Pins in `sources.tsv`:** each object is pinned by S3 `versionId`, size, the full-object CRC64-NVME, ETag, the header identity fields and a SHA-256 frozen after the first download. Download, build and verify all enforce the pins.
- **License:** public domain. The MAST Data Use Policy says: "Most data hosted at MAST are in the public domain (see: open data), and therefore do not have restrictions on use."
  - The restricted subsets are exclusive-access data, CC BY 4.0 HLSPs, and the copyrighted DSS/GSC. Exclusive-access data include commissioning embargoes, and the policy says they cannot be retrieved anonymously before expiry.
  - These files are mission pipeline products under `jwst/public/`, retrieved anonymously and released in 2022.
  - `download.sh` re-fetches the page (best effort) and fails if the public-domain sentence disappears or JWST joins the copyrighted list.
- **Privacy:** the primary header carries `PI_NAME`. No header text goes into samples or index rows.

## Shape and conversion

- **Natural record:** one detector exposure's SCI ramp cube, `(group, row, column) = (8, 2048, 2048)`, 33,554,432 values. There is no cropping or tiling, and the 4-pixel reference border is kept.
- **Regime:** asserted on every file in download, build and verify:
  - NIRCam SW, `NRC_IMAGE`, `CLEAR`, `FULL`
  - `MEDIUM8`, `NGROUPS = 8`, `NINTS = 1`, `NFRAMES = FRMDIVSR = 8`, `GROUPGAP = 2`
  - `COMPRESS = F`, `DATAPROB = F`, `ENG_QUAL = OK`
  - program 02736, observation 001, visit 001
  - SCI `BITPIX = 16`, `BZERO = 32768`, `BSCALE = 1`, `BUNIT = DN`, no `BLANK`
  - Same-size SHALLOW4 files from other programs are excluded by header, never by size.
- **What varies:** the detector (all eight: NRCA1–4, NRCB1–4), the filter (6 F090W + 6 F200W) and the dither position.
  - NRCA2, NRCA3, NRCB1 and NRCB4 appear once per filter.
  - F150W is absent because its SW uncal objects are not in the bucket.
- **Conversion:**
  1. Walk the 2,880-byte FITS headers; the full HDU chain must be PRIMARY, SCI, ZEROFRAME, GROUP, INT_TIMES, ASDF and must end at the file size.
  2. Read the 67,108,864-byte big-endian int16 SCI unit and add BZERO 32768. This is the standard FITS unsigned-16 convention, so the values are the exact native uint16 DN.
  3. Write the cube as little-endian uint16 in FITS axis order.
  - ZEROFRAME, GROUP, INT_TIMES and ASDF are not emitted.
- **Missing values:** none are masked. The cubes keep saturated 65535 readings and 0 DN readings.
  - **Judge correction:** of the 14 pixels with 0 DN readings, 8 drop to 0 mid-ramp after a large deposit. The other 6 are dead pixels that read 0 in all 8 groups: 5 on NRCA1 F090W and 1 on NRCB3 F200W. The README and manifest describe all of them as mid-ramp drops.

## Accepted output

| Item | Value |
|---|---|
| Primary samples | 12 |
| Primary values | 402,653,184 |
| Primary bytes | 805,306,368 |
| Sample size | 33,554,432 values (67,108,864 bytes) each |
| Per-cube minimum | 0 – 2,387 DN |
| Per-cube maximum | 62,062 – 65,535 DN |
| Distinct values per cube | 24,163 – 27,599 |
| 65535 readings | 113 total (0 – 73 per cube) |
| 0 DN readings | 80 total (0 – 46 per cube) |
| Interior-row mean, group 1 → group 8 | rises 70 – 130 DN in every cube (bias about 8,500 – 10,500 DN) |
| Download | 906,681,600 bytes (12 files) |
| Aggregate sample SHA-256 | `0a8eb60b386ddbd76b1fa64347629152fe609e8dd5e49b7829dd3afc73d59ef7` |

**Why 12 samples:** each natural record is 67.1 MB, so the 1 GB cap allows at most 14 whole records. The source offers 84 eligible files in this observation, so the count is limited by record size, not by the source. 805 MB is far above the roughly 100 MB that downstream selection takes per family.

**Caveats:**
- All samples come from one target field on one observing day.
- Same-detector pairs share the detector's fixed bias pattern. For NRCA2: 1.45% of group-1 pixels are exactly equal, the median |diff| is 19 DN, and the correlation of ramp increments is 0.009.
- MAST reprocesses JWST data. A future rewrite will break the version, CRC and SHA pins loudly, and `discover.sh` would then need to be re-run.

## Judge checks

- **Gate:** `gate.py` PASS with no warnings; primary values 402,653,184, bytes 805,306,368, 12 samples, median 33,554,432, width 16.
- **verify.sh** (run by the judge): `verify ok samples=12 bytes=805306368 detectors=8 filters=['F090W', 'F200W']`, exit 0.
- **Tamper test:** in a scratch `DATA_DIR` that symlinked the downloads, index and other samples, one flipped bit in the NRCA3 F090W sample made verify fail with "emitted sample differs from the independently re-derived SCI cube".
- **Script timing and pins:**
  - `download.sh` (18:44), `check_payload.py` and `jwst_uncal.py` predate the driver's download (19:20–19:22).
  - The `sha256` column added to `sources.tsv` afterwards (19:26) equals `download_plan.tsv` for all 12 files.
  - The driver's download log shows evidence_ok, liveness_ok, and 12 files fetched with the pinned CRC64-NVME.
- **Local-only build:** `build.sh` and `build.py` have no curl, urllib or http use. A quoted-glob grep found no credential patterns in any recipe file.
- **Byte inspection (stdlib):**
  - **Headers:** an independent header walk found SCI data at byte 25,920 with BITPIX 16, BZERO 32768 and NAXIS (2048, 2048, 8, 1).
  - **Exact decode:** a whole-cube `struct.unpack('>h') + 32768` decode of NRCA1 F090W and NRCB3 F200W had 0 mismatches against the `<H` samples.
  - **Distributions:**
    - group-1 percentiles for NRCA1 (0.1 / 50 / 99.9 %): 3705 / 8766 / 13263 DN
    - interior g8−g1 (1 / 50 / 99 %): 34 / 53 / 883 (NRCA1) and 45 / 61 / 999 (NRCB3)
    - g2−g1 median: 0 (NRCA1, F090W) and 25 (NRCB3, F200W), matching the higher F200W sky level
    - reference columns: g8−g1 within about ±10 DN
  - **Runs and entropy:** the longest run of equal adjacent values in group 4 is 2–3; zlib-6 on group 1 gives 1.128–1.177×.
  - **Zero and saturated readings:** the census found the 14 zero-reading pixels (6 dead for the whole ramp, 8 mid-ramp drops) and flat saturated 65535 pixels.
  - **Orientation:** FASTAXIS is ±1 on all 12 files, so the fast axis runs along x everywhere.
- **Rights:** the judge read the full text of the MAST data-use page that `download.sh` saved (81,786 B, sha256 `f309e1b4…37e2c3`, byte-identical to the IUE judge's copy).
  - It confirms the public-domain default and that exclusive-access and commissioning embargoes lapse into unrestricted public use.
  - The copyrighted list holds only DSS/GSC, and HLSPs are CC BY.
  - The headers show `ORIGIN = STSCI`, `DATAMODL = Level1bModel` and `CATEGORY = COM`, consistent with ERO commissioning-period mission data released in July 2022.
  - The AWS Open Data registry page and GitHub could not be reached through the proxy, so that extra source was not consulted.
- **Novelty:** `novelty.py` was run with the stpubdata `jwst/public/` URL, the `stpubdata` and `archive.stsci.edu` hosts, and the terms jwst / nircam / uncal / webb / stsci / h2rg / up-the-ramp / ramp / infrared.
  - The only URL match is this staging recipe; the registry and downstream corpus have no JWST material.
  - A wider fits / telescope / ccd / detector scan found only other missions and modalities.
  - Label: `new_source`.
