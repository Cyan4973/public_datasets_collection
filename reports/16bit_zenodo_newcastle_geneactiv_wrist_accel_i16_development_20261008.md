# GENEActiv wrist accelerometer counts int16: development report

## Outcome

Accepted `zenodo_newcastle_geneactiv_wrist_accel_i16`. The recipe takes 13 complete left-wrist GENEActiv device recordings from the Newcastle polysomnography and accelerometer study 2015. Each recording becomes one sample of native 12-bit two's-complement x, y, z ADC counts, sign-extended and interleaved per frame as little-endian int16.

This is the first raw wearable human-motion accelerometer material in the local corpus. Inertial accelerometry already exists at 16 bits: locally as honeybee vibration PCM (`zenodo_accelerometer_pcm16`) and Bosch CNC vibration (`bosch_cnc_milling_ciss_vibration_i16`), and downstream as UCI HAR smartphone float16 (`har_total_acc`, `har_body_acc`). The novelty label is therefore `new_content_same_modality`. Measured breadth (zlsim) is STRONG: the nearest family is 0.128 away (`unicode_bmp_gutenberg`).

## Source and rights

| Item | Value |
| --- | --- |
| Source | Zenodo record 1160410, v1.0, published 2018-01-25 |
| DOI | 10.5281/zenodo.1160410 |
| Authors | van Hees, Charman, Anderson |
| Protocol paper | PLoS ONE 10(11): e0142533 |
| Deposit | one file, `dataset_psgnewcastle2015_v1.0.zip` |
| ZIP size | 962,798,652 bytes |
| ZIP md5 | `8ebadbc55cb0e76230f293fc6d53f504` |
| License | CC BY 4.0 (`metadata.license.id = "cc-by-4.0"`, `access_right = "open"`), covering the single deposited ZIP |

`download.sh` re-checks the license, access right, DOI, size and md5 on every run.

### Privacy

- The GENEActiv headers contain subject fields: date of birth, sex, height, weight and notes. The record description also says these header IDs are stale values left over from previous device users.
- Headers are parsed in memory only, to assert device type, frequency, range and page count. No header value is emitted, indexed or logged.
- `participants_info.csv` (diagnosis, age, sex) and the PSG score files are never requested.
- Participants appear only as study numbers.
- The index keeps the public ZIP member names, which contain the device serial and the recording datetime.

## Shape and conversion

### Download

- `download.sh` range-fetches the 10,396-byte central directory plus EOCD.
- It re-derives the selection on every run: left-wrist members; uncompressed size ≤100,000,000 bytes (26 of 28, which drops the multi-day MECSLEEP23 and MECSLEEP34); ordered by participant; every second one.
- It then range-fetches the 13 pinned member spans, 194,859,344 bytes in total. Every chunk must return 206 with the exact Content-Range.
- Resume is by manual offset, with a stall-based speed limit.

### Decode

1. Inflate each member as raw DEFLATE and check CRC32 and size.
2. Validate every page: 8 metadata keys in order, sequence number equal to the page index, page frequency 85.7, and a data line of exactly 3,600 hex characters.
3. The page count must equal the header's `Number of Pages`.
4. Decode each 48-bit word: x = sext12(w>>36), y = sext12(w>>24), z = sext12(w>>12).
5. Drop the light (10 bits), button and reserved bits. Temperature, battery and page time are never emitted.
6. No calibration is applied.

### Error and degeneracy rules

- Any structural error is fatal.
- These are also fatal: a constant sample or axis, fewer than 256 distinct codes, mode share above 50%, or more than 50% of pages inside quasi-static runs of 60 min or more.

## Accepted output

| Item | Value |
| --- | --- |
| Samples | 13: participants 01, 10, 17, 27, 29, 32, 38, 42, 48, 50, 52, 56, 59 |
| Primary values | 233,424,900 |
| Primary bytes | 466,849,800 |
| Pages per recording | 12,336-24,672 (259,361 in total), about 12.0-24.0 h |
| Smallest sample | 11,102,400 values |
| Median sample | 19,001,700 values |
| Largest sample | 22,204,800 values |
| Distinct codes per recording | 1,080-1,437 |
| Mode share | 0.9-2.6% |
| Clipped full-scale codes | 0-37 per recording (137 in total) |
| Quasi-static pages | 83-92% (aggregate 87.4%) |
| Pages in quasi-static runs of 60 min or more | 0-24.8% (aggregate 9.3%) |
| Longest quasi-static run | 2.87 h |
| Aggregate SHA-256 of per-sample SHA-256s | `57f8fe9d02612a39df85c81b4e9a54d11f2eec8ed9c9e5ffd74d130746bb212d` |

## Judge checks

- **Gate.** `gate.py` PASS with no warnings.
- **Verify.** I re-ran `verify.sh`: exit 0 in 89 s. Every page was re-decoded with the per-word reference decoder and compared byte for byte, and every index field was recomputed.
- **Build locality.** `build.sh` uses only local files: selftest, local central-directory check, local spans.
- **Independent decode.** My own zlib/struct decoder of MECSLEEP10 and MECSLEEP48 matches the samples exactly on the checked pages (first, middle and last) and on a stride-97 scan, with 0 mismatches.
  - The data-line count equals the header page count.
  - The light/button bits are non-zero in the source and correctly dropped.
- **Physical plausibility.** Median gravity magnitude on still pages is 251-267 counts in 6 recordings, which matches about 256 counts/g uncalibrated.
  - The first frame of MECSLEEP01 is (-13, 248, -106), which matches the card's probe.
  - Deltas are noise-dominated (0, ±1, ±2), and page-boundary jumps are close to within-page jumps.
- **Homogeneity.** I read the non-personal header fields of all 13 recordings: model 1.1, firmware Ver1.30, range -8 to 8, resolution 0.0039 g, 85.7 Hz. Gains are within about 2% of 25,600 and offsets within ±17 counts.
- **License.** I confirmed it live from the Zenodo record API.
- **Privacy.** A grep of logs, index, filtered stats and README for subject header fields found nothing. The scripts contain no credentials.
- **Novelty.** `novelty.py --url` found a host-only match. The `--type`/`--instrument`/`--archive` and `--vocabulary` runs show inertial accelerometry at 16 bits locally (honeybee, Bosch CNC). I checked the downstream 16-bit HAR bytes and they are float16 smartphone g.
- **Wording nits (non-blocking).**
  - The manifest says "12 h or 24 h device sessions". One session was configured for 18 h, and one 66 h configuration ended at 20.5 h.
  - The README says "15 h to 24 h", but the shortest non-12 h recording is 17.2 h.
  - The page counts in the manifest and README are exact.
- **Archive host.** This is at least the third Zenodo acceptance in this effort, so the driver's archive-host sign-off applies.
