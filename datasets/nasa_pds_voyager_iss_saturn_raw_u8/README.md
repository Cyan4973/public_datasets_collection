# nasa_pds_voyager_iss_saturn_raw_u8

Raw 8-bit vidicon frames from the Voyager 2 Imaging Science Subsystem (ISS)
narrow-angle camera, taken during the August 1981 Saturn encounter. Each
sample is one complete 800 × 800 uint8 frame of uncalibrated data numbers
(DN). The frames show the Saturn disk or crescent and the rings, together
with the vidicon dark-current background, reseau marks, blemishes, radiation
spikes, saturated pixels, and occasional zero-filled telemetry-dropout lines.
They are exactly as losslessly decompressed from the archival IMQ EDR files.

## Source

- PDS Rings Node data set `VG1/VG2-S-ISS-2/3/4/6-PROCESSED-V1.0`, volume
  `VGISS_0005` (Voyager 2 "selected Saturn images", FDS 43901.59-44304.45),
  served from the public anonymous bucket
  `https://asc-pds-voyager.s3.us-west-2.amazonaws.com/VGISS_0005/`.
- Product: `Cnnnnnnn_RAW.IMG` (`PRODUCT_TYPE = DECOMPRESSED_RAW_IMAGE`) with a
  detached `Cnnnnnnn_RAW.LBL`. The label says the image "is the result of
  decompressing the corresponding source image Cnnnnnnn.IMQ as found on one
  of the Voyager ISS CD-ROMs ... expanded using VICAR routine VGRCDCOPY",
  800 × 800 unsigned bytes with a 224-byte prefix on each line.
- Only the RAW products are mirrored on this bucket. The CLEANED, CALIB and
  GEOMED derivatives are not, and they would be processed products anyway.

## Selection (`discover.py`, pinned in `sources.tsv`)

The rule is applied to `VGISS_0005/INDEX/INDEX.TAB` (8,412 rows, 1,402 raw
images). `download.sh`, `build.py` and `verify.py` re-derive it from the
same index.

Keep rows that meet all of these:
- `PRODUCT_TYPE = DECOMPRESSED_RAW_IMAGE`, `SPACECRAFT_NAME = VOYAGER 2`,
  `MISSION_PHASE_NAME = SATURN ENCOUNTER`
- `INSTRUMENT_NAME = NARROW ANGLE CAMERA`
- `SCAN_MODE = 3:1`, `EDIT_MODE = 1:1` (full resolution), `GAIN_MODE = LOW`
- `TARGET_NAME` is `SATURN` or `S RINGS`
- `SHUTTER_MODE` is not `BODARK` (dark frames)
- not under `CALIB/`, `DATA_ANOMOLY = NONE`, exposure not null

Result:
- 339 frames: 145 SATURN, 194 S RINGS
- 1981-08-22T16:29:35 to 1981-08-31T02:34:22
- filters: CLEAR 232, GREEN 95, UV 5, VIOLET 4, BLUE 2, ORANGE 1
- exposures 0.36-15.36 s
- shutter modes: NAONLY 115, BOTSIM 125, BOTALT 99

Every image is a single-part S3 object of 823,296 bytes, so its ETag is its
MD5. `sources.tsv` pins the URL, size, MD5 and Last-Modified of each image
and label. `download_plan.tsv` records the SHA-256 of each fetched image.

Why scan rate 3:1 rather than 1:1: the screener suggested 1:1, but at
Saturn the standard narrow-angle readout was 3:1. VGISS_0005 has 603
narrow-angle 3:1/1:1 frames but only 29 at scan 1:1 (edit 1:1), and only 8
of those 29 target SATURN or S RINGS. One readout rate is kept because the
dark-current level depends on it (DOCUMENT/PROCESSING.TXT, appendix).
PROCESSING.TXT also says that a VGRCDCOPY bug writing 1:1 into the headers
of 3:1 Saturn images was corrected, and every selected VICAR `LAB03` reads
`SCAN RATE  3:1`.

Volume: 339 × 823,296 = 279,097,344 image bytes, plus 1,256,790 label bytes,
3,335,007 index bytes and the 16,978-byte AAREADME, about 283.7 MB in total.

## Decode, and the PDS label erratum

The VICAR label of each file reads `LBLSIZE=1024 RECSIZE=1024 NLB=2 NBB=224
NL=800 NS=800 EOL=1`, so the layout is:

| bytes | content |
|---|---|
| 0-1023 | VICAR label |
| 1024-3071 | 2 VICAR binary-label records (engineering header; 256 × uint32 DN histogram) |
| 3072-822271 | 800 image records: 224-byte binary prefix + 800 uint8 DN |
| 822272-823295 | VICAR extension label |

The detached PDS label says `^IMAGE = ("...RAW.IMG", 2)` and
DOCUMENT/TUTORIAL.TXT says "1 header record". Both ignore the two VICAR
binary-label records. Reading from record 2 would emit the engineering
header and the histogram as image lines 1-2 and drop the last two real
lines. The probe confirmed the VICAR offset:

- For C4390159 (no dropouts), the uint32 histogram in the second
  binary-label record equals the DN histogram of records 4-803 exactly (L1
  difference 0). Against records 2-801 the L1 difference is 2,902.
- Bytes 22-24 of each line prefix hold the FDS clock count (u16 LE modulo-16
  count, u8 modulo-60 count). On the first image line (record 4) it equals
  the frame's image number.

Conversion: for each of the 800 image records, drop the 224-byte prefix,
keep 800 bytes, and concatenate the rows in file order
(`LINE_DISPLAY_DIRECTION = DOWN`, `SAMPLE_DISPLAY_DIRECTION = RIGHT`). The
result is 640,000 bytes written to
`samples/nasa_pds_voyager_iss_saturn_raw_u8/vg2_issn_saturn_raw_dn_u8/Cnnnnnnn.u8`.
DN values are unchanged. No prefix, header or label byte reaches a sample.

## Missing values and exclusion

Telemetry dropouts appear as image lines whose 800 DN are all 0 (the probed
C4415435 has 22 such lines). They are kept as-is in emitted frames, as are
DN 0 dark pixels and DN 255 saturated pixels. One deterministic rule is
shared by build and verify: a frame is not emitted if it has more than 40
all-zero image lines (5 %) or fewer than 16 distinct DN. Excluded frames are
listed in `filtered/.../ingest_stats.json`, and the manifest `sample_count`
is the realized number of emitted frames.

Realized build (2026-10-05):
- 2 of the 339 pinned frames are excluded: C4414941 (68 fill lines) and
  C4415358 (59), both SATURN, outbound
- 337 frames emitted (143 SATURN, 194 S RINGS), 215,680,000 bytes
- 33 emitted frames have 1-39 fill lines
- 255 of the 337 reproduce the embedded VICAR histogram exactly, which
  confirms the NLB=2 offset across the set; the rest differ because of
  dropout lines or spikes
- frame mean DN ranges from 18.9 to 244.2 (median 127.6); 93 frames have a
  mean below 30 (dark outbound crescents, ring-ansa scans, F-ring searches).
  Even the darkest still zlib-compress only to about 0.285, so they carry
  noise and reseau texture rather than flat fill
- 3 color-filter Saturn frames (C4391521, C4391535, C4391542) are 61-83 %
  saturated at DN 255 (overexposed); they are kept as genuine raw DN

## Checks

- `download.sh`:
  - one-byte liveness GET
  - AAREADME (pinned) must contain the data-set id and citation request
  - INDEX.TAB/LBL pinned; the re-derived selection must equal `sources.tsv`
  - per frame: size and MD5 pins, PDS label keywords (VG2, ISSN, 3:1, 1:1,
    LOW, target, 800 × 800 × 8-bit, 224-byte prefix, IMAGE_NUMBER), VICAR
    keywords and `LAB02`/`LAB03`/`LAB04`, the extension label position, and
    the first-line prefix FDS count
  - resumable `curl -C -` with stall detection
- `build.py`: repeats the pins and the selection, decodes, applies the
  exclusion rule, rejects duplicates, and writes the index and
  `ingest_stats.json`.
- `verify.py` does not import `vgiss.py`. It:
  - re-parses INDEX.TAB as CSV
  - re-checks the labels with its own parser
  - recomputes each frame from the file's own VICAR label offsets
    (`LBLSIZE + NLB × RECSIZE`, `NBB` prefix)
  - re-applies the exclusion rule
  - byte-compares every sample
  - checks index fields, min/max/distinct, SHA-256, duplicates, manifest
    count and bytes, and the aggregate histogram (at least 200 DN levels; no
    single DN holding more than half of all pixels)

Self-tests (scratch under `/tmp/autocollect/voyager/`):
- synthetic VICAR frames with trap bytes in the binary-label records came
  out byte-exact; a 41-fill-line frame was excluded and a 22-line one kept
- verify failed on a wrong manifest count and on a flipped sample byte
- the two real probe frames (C4390159, C4415435) built and verified
- `download.sh` was dry-run offline with a stub curl (fetch, cache reuse,
  MD5-triggered refetch)

## Homogeneity

One spacecraft (Voyager 2), one camera (narrow angle), one readout mode
(scan 3:1, full-resolution edit 1:1, low gain), one encounter week, one
decompression path (VGRCDCOPY), and one target class (Saturn disk and ring
system). Filter, exposure and scene vary naturally. Wide-angle frames,
Voyager 1, other scan rates, partial-resolution edits, satellites, sky and
calibration frames are excluded rather than mixed in.

## Rights and citation

NASA mission data archived by the NASA Planetary Data System. Under the
NASA SMD scientific information policy, SMD-funded research data are made
publicly available and openly shared; this is the same basis as the
accepted `nasa_pds_cassini_vims_qube_i16` and `nasa_pds_mastcamz_raw_i16`
recipes. The volume AAREADME imposes no restriction and asks for this
citation:

> Showalter, M.R., M.K. Gordon, and D. Olson, VG1/VG2 SATURN ISS PROCESSED
> IMAGES V1.0, VGISS_0001-0038, NASA Planetary Data System, 2006.

It also asks for an acknowledgement of the Voyager Imaging Team led by
Dr. Brad Smith. science.nasa.gov, pds.nasa.gov and pds-rings.seti.org are
unreachable through the collection proxy, so `download.sh` checks only the
AAREADME.

## Novelty

`tools/autocollect/novelty.py` found no URL or registry match. The nearest
accepted family is `mast_iue_swp_raw_image_u8`: 8-bit raw SEC-vidicon frames
of ultraviolet spectra from an Earth-orbit observatory. This recipe is the
same broad modality (raw vidicon DN frames) but a new source and scene type:
outer-planet imaging of a disk and ring system. So the novelty is
`new_source`, not a new modality. No outer-planet raw camera frames exist
locally at any width; `nasa_pds_cassini_vims_qube_i16` is an imaging
spectrometer cube from a different mission.
