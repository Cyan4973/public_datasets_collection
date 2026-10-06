# Cassini RADAR Titan SAR BIDR sigma0 uint8 development

## Outcome

Accepted `nasa_pds_cassini_radar_bidr_sigma0_u8`. It collects every USGS-produced Cassini RADAR `BIBQH` product of Titan from flyby Ta (T00A, 2004-10-26) through T19 (2006-10-09). That is 22 SAR imaging segments from 10 flybys. Each segment is emitted as its native uint8 incidence-angle-corrected sigma0-dB image at 128 pixels/degree (about 351 m/pixel) in oblique cylindrical projection.

This is the first planetary SAR image family in the local corpus, and the first 8-bit SAR imagery. Earth SAR exists only as `sentinel1_grd_measurement_u16`, which is C-band linear amplitude and not map-projected. The other Cassini recipe, `nasa_pds_cassini_vims_qube_i16`, is a different instrument, archive host and file set. Novelty kind: `new_source`.

## Source and rights

- **Source:** the anonymous USGS Astrogeology PDS Cassini S3 bucket `asc-pds-cassini` (us-west-2), with PDS3 volumes `CORADR_*` and data set `CO-SSA-RADAR-5-BIDR-V1.0`.
- **Download:** 22 product ZIPs, 89,704,750 bytes.
- **Pinning:** `sources.tsv` (SHA-256 `b59c6fabe0d1941ac6bc85f65367f9aa713799700cb974438643f7c5b5895caf`) records for each product:
  - ZIP size and MD5 (single-part S3 ETag)
  - ZIP member CRC32 and compressed size
  - uncompressed `.IMG` size and MD5
  - label geometry, CHECKSUM and start/stop times
- **Rights:** U.S. public domain.
  - Every label declares `PRODUCER_INSTITUTION_NAME = "U.S.G.S. FLAGSTAFF"` and `PRODUCER_ID = USGS`.
  - `ERRATA.TXT` item 8 states: "The byte-valued backscatter images were produced by USGS."
  - The USGS Copyrights and Credits policy states: "USGS-authored or produced data and information are considered to be in the U.S. Public Domain." The accepted `usgs_geomag_observatory_minute_f32` and `usgs_shakemap_ground_motion_f32` use the same page.
  - NASA SMD open scientific data policy (precedent: `nasa_pds_cassini_vims_qube_i16`) applies as well.
- **Safety:** no credentials and no personal data.

## Shape and conversion

Each natural record is one BIDR product, i.e. one SAR imaging segment of one flyby. Each ZIP holds a single DEFLATE member `<product>.IMG`. That member is a PDS3 fixed-length file: an attached label (`RECORD_BYTES` 1024–4864, `LABEL_RECORDS` 1–5), then the `IMAGE` object with one line per record.

The recipe inflates the member, validates the label, and copies `LINES*LINE_SAMPLES` bytes starting at `(^IMAGE-1)*RECORD_BYTES`, unchanged.

Every label asserts the same constants:

| Field | Value |
|---|---|
| `SAMPLE_TYPE` | `UNSIGNED_INTEGER` |
| `SAMPLE_BITS` | `8` |
| `SCALING_FACTOR` | `1.0000012E-01` |
| `OFFSET` | `-2.0100010E+01` |
| `MISSING_CONSTANT` | `0` |
| `MAP_RESOLUTION` | `128.0<PIX/DEG>` |
| `MAP_PROJECTION_TYPE` | `OBLIQUE CYLINDRICAL` |
| `TARGET_NAME` | `TITAN` |

The physical value is dB = DN × 0.10000012 − 20.10001.
- DN 1 is the -20 dB clip floor (ERRATA item 10).
- DN 251 (+5 dB) is the observed top.
- DN 0 is fill outside the swath. It is preserved in place, never dropped or imputed.

**Excluded:**
- the single Enceladus `BIBQH` product (OFFSET -15.1)
- the float BIDR kinds and the M/L backplanes
- the other resolutions
- `RADAR/superseded/`
- flybys after T19, because the full Titan H set is 159 products and 3.68 GB, over the cap

## Accepted output

| Measure | Value |
|---|---|
| Primary series | `cassini_radar_bidr_sigma0_db_u8` (uint8) |
| Samples | 22 (10 flybys: T00A, T3, T7, T8, T13, T15, T16, T17, T18, T19) |
| Primary values / bytes | 343,474,176 |
| Sample size range | 2,703,360 to 45,072,384 values (1408×1920 to 16768×2688) |
| Median sample | 8,781,824 values (gate) |
| Missing (DN 0) fraction | 70.26% overall, 56.3–94.2% per product |
| Non-missing pixels | 102,140,599; minimum 182,572 per product |
| Distinct non-missing levels per product | 246–251 |
| DN 1 share of non-missing pixels | 3.99% |
| Distinct sample SHA-256s | 22 of 22 |

Aggregate SHA-256 of the samples concatenated in index order: `37644a3cae84931ccbb14890d22031e65c5409a48219ee4675168c130c73bf68`.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/nasa_pds_cassini_radar_bidr_sigma0_u8` passed with no warnings.
- **Verify:** `bash verify.sh` passed (verify_ok, 22 samples, 343,474,176 bytes, 13.4 s). Its decoder is independent: a hand-parsed ZIP header, raw zlib, separate label regexes, CRC32, IMG MD5 and label CHECKSUM, then a byte comparison of every sample.
- **Local files only:** build.sh and verify.sh contain no network calls.
- **Bytes, all 22 samples (stdlib Python):**
  - non-missing means are -4.5 to -10.2 dB, plausible for Titan Ku-band backscatter
  - every DN 1..251 occurs, with no combing (adjacent-bin ratio 0.987–1.011)
  - neighbouring pixels differ by 3.9–42.6 DN against 27–88 DN for random pairs, so the images have natural spatial structure
  - the swath is mostly one contiguous run per line
  - non-missing pixels zlib-compress only to 0.62–0.91 (speckle)
  - no line is duplicated within or across samples
  - five high-altitude segments are smoother (oversampled onto the fixed grid); this is the same product type, not a different regime
- **Scope:** a live S3 listing of `CORADR_0030`–`0125` shows exactly the 22 pinned `BIBQH` products for T00A–T19.
- **Rights:**
  - ERRATA item 8 was confirmed in the live `CORADR_0035/ERRATA.TXT`.
  - One attached label was inspected for producer and constants.
  - The live USGS policy page is blocked by the proxy (403). Its quote was confirmed verbatim from the copy that the accepted `usgs_shakemap_ground_motion_f32` download saved locally on 2026-08-27.
- **Novelty:**
  - `novelty.py --url https://asc-pds-cassini.s3.us-west-2.amazonaws.com/RADAR/ --terms cassini radar bidr titan sigma0 backscatter sar` matched only the candidate itself.
  - `--url asc-pds-cassini --terms coradr` matched nothing.
  - Labelled `new_source` rather than `new_modality`, because SAR imagery exists locally at 16 bits.
- **Volume:** 22 samples is at the ~20 'acceptable' level, not 'well under' it. The source offers 159 samples, but they total 3.68 GB, which exceeds the 1 GB cap. 343 MB from 89.7 MB of downloads is well past the ~100 MB downstream need.
