# NASA IRIS level-1 FUV spectrograph frames, int16: development report

## Outcome

`nasa_heliocloud_iris_l1_fuv_frames_i16` is accepted after one repair cycle.

- **The family:** whole level-1 CCD frames from the far-ultraviolet (FUV) spectrograph of NASA's Interface Region Imaging Spectrograph (IRIS), as native int16 DN.
- **First submission:** the judge found two value lattices mixed in one family:
  - 23 frames used onboard LUTID 0, with no companding;
  - 17 frames used LUTID 4, onboard square-root companding.
- **The repair:**
  - restricted the regime to LUTID 0;
  - added an explicit unit-DN lattice check in both build and verify;
  - widened the index scan from 60 to 120 CSVs and re-selected 40 frames;
  - quoted the IRIS project's own open-data statement.
- **Novelty:**
  - This is a new source and new material: the corpus has no other HelioCloud data and no other solar UV slit spectrograph.
  - It is the second raw space-detector frame family at 16 bits in this collection effort, after `mast_jwst_nircam_sw_uncal_ramps_u16`.

## Source and rights

- **Source:** NASA GSFC HelioCloud public bucket `gov-nasa-hdrl-data1`, prefix `sdac/iris/iris_data/level1/YYYY/MM/DD/HHHMM/*_fuv.fits`. Access is anonymous HTTPS and the bucket is not requester-pays.
- **Pins:** 40 objects, 112,109,760 bytes. Each has its size, MD5 (equal to the S3 ETag), full-object SHA-1 (`x-amz-checksum-sha1`) and SHA-256 recorded in `sources.tsv`. The SHA-256 of `sources.tsv` itself is `28f5cdf8...`.
- **Selection:** the pins come from an authoring-time scan of 120 of the 1,439 minute-of-day index CSVs. `download.sh` fetches only the pinned keys.
- **Rights:** two open-data policies, not a named license. This is the same basis as the accepted `nasa_heasarc_nicer_pi_i16` and `nasa_heasarc_batse_cont_counts_i16`.
  - **IRIS project page** (`iris.lmsal.com/data.html`, sha256 `b0b34efe...`): "IRIS has an open data policy. When you publish work based on IRIS data, please acknowledge IRIS as follows: …"
  - **NASA SMD Science Information Policy** (sha256 `d1fdc2da...`): "NASA holds this information, including publications, data, and software, as a public trust ... be made publicly available". It also states "Mission data are released as soon as possible".
- **Conditions:**
  - Use the IRIS acknowledgement text and cite De Pontieu et al. 2014, Sol. Phys. 289, 2733.
  - The NASA AI guidance applies: do not attribute model outputs to NASA and do not use NASA insignia.

## Shape and conversion

**Natural record.** One level-1 FUV exposure is one FITS file. The file holds an empty primary HDU, then a BINTABLE `COMPRESSED_DATA` with these properties:
- `RICE_1` compression, one tile per image row (`ZTILE 4144x1`);
- `BLOCKSIZE 32`, `BYTEPIX 2`, `ZBITPIX 16`;
- no scaling or quantization keywords.

**Decoding.**
- Each row tile is decoded exactly as CFITSIO `fits_rdecomp_short` does, in pure standard-library Python.
- Each frame is written whole as 1096 x 4144 little-endian int16, row-major in FITS order.

**Validation.**
- The decoded frame must match the header's `DATASUM`/`CHECKSUM`, `DATAVALS`, `DATAMIN`, `DATAMAX` and `DATAMEDN` exactly, and `DATAMEAN` to within 1e-3.
- `verify.py` re-decodes every file with a separate byte-wise decoder and its own FITS walker, then byte-compares every sample.

**Regime.** All 40 frames share:
- `IMG_PATH` FUV and `IMG_TYPE` LIGHT;
- `CAMERA` 1, CRS 1541 ("Full WL coverage, 1x1");
- `SUMSPTRL = SUMSPAT = 1`;
- readout rows 25-1072, columns 1-2048 and 2097-4112;
- `LUTID 0`.

**Missing values.**
- Pixels that were not read out keep the source `BLANK -32768`: 282,752 per frame, 6.23%.
- Both build and verify require the BLANK set to equal exactly the complement of the readout regions.

## Accepted output

- **Primary samples:** 40, each 1096 x 4144 = 4,541,824 int16 values (9,083,648 bytes).
- **Totals:** 181,672,960 primary values and 363,345,920 primary bytes.
- **Valid pixels:** 4,259,072 per frame (170,362,880 in total).
- **OBSIDs:** 3893012099 x18, 3690015104 x15, 3690011140 x2, 3882010194 x2, and one each of 3690011143, 3690010304 and 3893010094.
- **Years:** 2014 2, 2015 3, 2016 3, 2017 6, 2018 6, 2019 6, 2020 5, 2021 5, 2022 4.
- **Exposures:** 30 s x21, 60 s x15, 15 s x4.
- **Pointings:** 13 within 500 arcsec of disk centre, 17 beyond 850 arcsec.
- **Value statistics:**
  - frame medians 111-163 DN;
  - 359-1,350 distinct valid values per frame;
  - valid range 0-16383 DN.
- **Download:** 112,109,760 bytes.
- **Aggregate decoded SHA-256** (sample files in path order): `508681dfca22fab296649ee0ee41395eddc1654bcf2e87ec177ccc3d7bed148a`

## Caveats

- **Low entropy:** most pixels sit on a pedestal near 110-165 DN with read noise. In the median frame, 95.6% of read-out pixels lie within ±20 DN of the frame median.
- **OBSID concentration:** two OBSIDs supply 33 of the 40 frames, although they cover many dates and solar targets.
- **No 2013 frames:** no LUTID-0 frame from 2013 turned up in the scan.
- **Partial index scan:** discovery read 120 of the 1,439 index CSVs, not the whole index.
- **Calibration split is inferred:** treating OBSIDs that start with 4 as calibration programs comes from the data, not from IRIS documentation.
- **Excluded sibling lattice:** LUTID-4 frames (onboard square-root companding) are excluded. They could form a separate family.
- **Documentation nits, not fixed:**
  - the header comment in `discover.sh` says 60 CSVs, but the script scans 120;
  - re-running `discover.py select` would rewrite `sources.tsv` without the SHA-256 column. This is authoring-only; `download.sh` still enforces MD5 and SHA-1.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/<id>` passed with no warnings.
- **Verify:** I ran `bash staging/<id>/verify.sh` myself.
  - It exited 0 in 11 s.
  - It reported 40 samples, 7 OBSIDs, 9 years and a BLANK fraction of 0.0623.
- **Local-only build:** I read `build.sh`, `build.py`, `selftest.py`, `verify.py`, `iris_fits.py`, `check_payload.py`, `discover.py` and `download.sh`.
  - Build and verify use only local files.
  - No credentials appear anywhere.
  - The build log shows the self-test passing, including the rejection of the synthetic companded frame.
- **Previous repair items:** all six were checked and done:
  1. the LUTID regime is enforced at download, build and verify;
  2. both build and verify run the lattice check;
  3. the selection was redone, with the index scan widened to 120 CSVs;
  4. all 40 rows are pinned;
  5. the IRIS rights quote is in the manifest and README;
  6. the documentation counts match the output.
- **Bytes** (stdlib Python, 8 samples decoded):
  - The BLANK layout is exact.
  - Valid values are 0-16383 with at most 3 saturated pixels per frame.
  - Unit-DN coverage is complete near the median, with no regular gaps higher up: in 60 s frames, 300-600 DN has 297-300 of 300 integers present and 600-1200 DN has 331-560 of 600.
  - Readout-port pedestal offsets are physical detector structure.
  - Same-OBSID pairs from adjacent dates have 6-8.5% equal pixels after median subtraction and a mean absolute difference of 3.9-7.9 DN, so there are no near-duplicates.
- **Header survey of all 40 FITS files:**
  - Constant across all 40: `LUTID` 0, `IICRSID` 1541, `CAMERA` 1, `QUALITY` 0, `BUNIT` 'Corrected DN', TSR/TER 25/1072.
  - No gain or compression keyword varies.
  - In the 5 frames with AEC flagged, the commanded shutter time still equals `EXPTIME`.
- **Rights:** I opened both evidence files and recomputed their SHA-256 values; both match the manifest. The quotes are verbatim.
- **Novelty:** `novelty.py` matched only the candidate's own staging and ledger rows.
- **Scope:** the realized scope recomputed from the index matches the README and manifest exactly.
