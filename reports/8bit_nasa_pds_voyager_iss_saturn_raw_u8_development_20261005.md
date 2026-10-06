# Voyager 2 ISS narrow-angle Saturn raw vidicon frames uint8 development

## Outcome

Accepted `nasa_pds_voyager_iss_saturn_raw_u8`. The recipe emits complete raw 8-bit vidicon frames from the Voyager 2 Imaging Science Subsystem narrow-angle camera, taken during the August 1981 Saturn encounter. Each sample is one 800 × 800 frame of uncalibrated data numbers (DN), exactly as decompressed losslessly from the archival IMQ files.

The family differs from the accepted `mast_iue_swp_raw_image_u8`. That recipe also holds raw 8-bit vidicon frames, but they record ultraviolet spectra on an Earth-orbit spectrograph camera. This recipe is outer-planet imaging of a planetary disk and ring system. It is a new source in a known modality.

## Source and rights

- **Source.** NASA PDS Rings Node data set `VG1/VG2-S-ISS-2/3/4/6-PROCESSED-V1.0`, volume `VGISS_0005` (Voyager 2 Saturn images, PUBLICATION_DATE 2006-08-15). It is served from the public anonymous bucket `https://asc-pds-voyager.s3.us-west-2.amazonaws.com/VGISS_0005/`.
- **Product.** `Cnnnnnnn_RAW.IMG` (`PRODUCT_TYPE = DECOMPRESSED_RAW_IMAGE`), 823,296 bytes each, with a detached `Cnnnnnnn_RAW.LBL`. The label says each image was "expanded using VICAR routine VGRCDCOPY" from the source IMQ file.
- **Pins:**
  - each of the 339 images and labels is pinned by size and MD5 (the S3 ETag of single-part objects) in `sources.tsv`
  - INDEX.TAB is pinned at 3,322,740 bytes, MD5 `9952de72d9a6013e5e0c0ae78de50c97`
  - INDEX.LBL is pinned at 12,267 bytes, and AAREADME.TXT at 16,978 bytes
  - `download_plan.tsv` records the SHA-256 of every fetched image
- **Download.** 283.8 MB fetched by the autocollect driver in about 16 minutes.
- **Rights:**
  - The basis is the NASA SMD scientific information policy for NASA mission data archived in PDS. Accepted precedents: `nasa_pds_cassini_vims_qube_i16` and `nasa_pds_mastcamz_raw_i16`.
  - The volume AAREADME imposes no use restriction. It asks only for the citation "Showalter, M.R., M.K. Gordon, and D. Olson, VG1/VG2 SATURN ISS PROCESSED IMAGES V1.0, VGISS_0001-0038, NASA Planetary Data System, 2006" and an acknowledgement of the Voyager imaging team led by Dr. Brad Smith. `download.sh` fails unless that text is present.
- **Safety.** No credentials and no personal data. The VICAR `USER` field is never emitted.

## Selection

The rule is applied to `INDEX.TAB` (8,412 rows) and re-derived independently by `download.sh`, `build.py` and `verify.py`. It keeps rows that meet all of these:
- `DECOMPRESSED_RAW_IMAGE`, `VOYAGER 2`, `SATURN ENCOUNTER`
- `NARROW ANGLE CAMERA`
- scan rate `3:1`, edit mode `1:1` (full resolution), gain `LOW`
- target `SATURN` or `S RINGS`
- shutter not `BODARK`, not under `CALIB/`, no data anomaly, exposure not null

Result: 339 pinned frames. Scan 3:1 was chosen over 1:1 because 3:1 was the standard narrow-angle readout at Saturn; only 8 Saturn or ring frames exist at 1:1 in this volume.

## Shape and conversion

From each file's own VICAR label (`LBLSIZE=1024 RECSIZE=1024 NLB=2 NBB=224 NL=800 NS=800 EOL=1`), the layout is:

| bytes | content |
|---|---|
| 0–1023 | VICAR label |
| 1024–3071 | 2 binary header records, including a 256 × uint32 DN histogram |
| 3072–822271 | 800 image records, each a 224-byte engineering prefix followed by 800 uint8 DN |
| 822272–823295 | VICAR extension label |

The PDS label's `^IMAGE = record 2` overlooks the two binary records. With `^VICAR_EXTENSION_HEADER = 804` and `FILE_RECORDS = 804`, record 2 would leave two records unaccounted for. The build therefore skips 3,072 bytes, drops each 224-byte prefix, and keeps 800 bytes per line, concatenated row-major in file order. DN values are unchanged.

Exclusion rule, shared by build and verify: a frame is dropped if more than 40 of its 800 lines are all zero (telemetry dropout) or if it has fewer than 16 distinct DN. This drops C4414941 (68 fill lines) and C4415358 (59). Kept frames with 1–39 fill lines (33 frames) are emitted as archived.

## Accepted output

- Pinned source frames: 339
- Excluded by the fill-line rule: 2
- Primary samples: 337 (143 SATURN, 194 S RINGS)
- Values per sample: 640,000 (800 × 800)
- Primary values and bytes: 215,680,000
- Time range: 1981-08-22T16:29:35 to 1981-08-31T02:34:22
- Exposures: 0.36–15.36 s
- Filters: CLEAR 231, GREEN 94, UV 5, VIOLET 4, BLUE 2, ORANGE 1
- Shutter modes: BOTSIM 123, NAONLY 115, BOTALT 99
- Frame mean DN: 18.9–244.2 (median 127.6)
- Distinct DN per frame: 60–256 (median 247)
- Aggregate: all 256 DN levels used; zero fraction 0.11%, DN-255 fraction 0.91%
- Frames whose stored histogram matches the emitted pixels exactly: 255 of 337
- Aggregate sample SHA-256 (hash of the per-sample hashes): `cea2664c208eba6e26455f39ebc914a99d9128a582ebb0c57a173976c4f31019`

Quality notes:
- 97 frames (29%) are near-blank background frames (99th percentile less than 20 DN above the median): vidicon dark level around DN 19, shading, noise and reseau marks, with no visible target. They are genuine raw readouts and compress only to 0.28–0.37 with zlib.
- 3 color-filter Saturn frames (C4391521, C4391535, C4391542) are 61–83% saturated at DN 255.

## Judge checks

- **Gate.** `python3 tools/autocollect/gate.py staging/nasa_pds_voyager_iss_saturn_raw_u8` passed with no warnings: 337 samples, median 640,000 values, width 8.
- **Verify.** I re-ran `bash staging/nasa_pds_voyager_iss_saturn_raw_u8/verify.sh`: exit 0, "verify ok samples=337 excluded=2 bytes=215680000 dn_levels=256". build.py reads only local files, and verify.py does not import the build module.
- **Independent decode.** On 12 random frames, my own `struct`-based script reproduced every sample byte-for-byte from offset 3072 with the 224-byte prefixes dropped:
  - the stored uint32 histogram matched the emitted pixels exactly (difference 0) at 3072, but was off by 2,896–3,190 at the PDS-label offset of 1024
  - the FDS count in the first line prefix equalled the image number in every case
- **Distribution scan.** I computed mean, standard deviation, distinct values, zero and saturated fractions, zlib ratio and consecutive-frame similarity over all 337 frames:
  - there are no exact duplicates, and consecutive frames share at most 55% identical bytes
  - the README's claims (mean range, 93 frames with mean below 30, 33 frames with fill lines) reproduce exactly
- **Visual check.** I rendered thumbnails of a ring close-up, the banded disk, a 15.36 s dark frame, a saturated frame and contrast-stretched dark frames. Geometry is correct, the reseau grid is regular, and no rows are shifted.
- **Rights.** I read the pinned AAREADME citation section myself. The NASA SMD policy page, the AWS open-data registry and GitHub are refused by the proxy. Rights therefore rest on the AAREADME plus the accepted NASA PDS precedents (VIMS, whose report validated the SMD wording, and Mastcam-Z).
- **Novelty.** `novelty.py --url https://asc-pds-voyager.s3.us-west-2.amazonaws.com/VGISS_0005/ --terms voyager vgiss vidicon saturn VGRCDCOPY asc-pds-voyager` matched only the candidate itself on URL. The downstream corpus and the registry had no matches. The nearest term hit is `mast_iue_swp_raw_image_u8`, which has a different source and scene type.
