# Cassini RADAR Titan SAR BIDR Backscatter (BIBQH, 128 pix/deg) UInt8

This recipe collects 22 complete Cassini RADAR synthetic-aperture-radar (SAR)
swath images of Titan from the NASA PDS BIDR archive
(`CO-SSA-RADAR-5-BIDR-V1.0`). Each sample is one product's native uint8 image:
Ku-band normalized backscatter cross-section (sigma0), corrected for
incidence angle and stored as dB DN, at 128 pixels/degree (about 351 m/pixel)
in an oblique cylindrical projection.

- Series: `cassini_radar_bidr_sigma0_db_u8`. Primary, `uint8`, one sample per
  product, shape `LINES x LINE_SAMPLES`, line-major.
- Scope: every `BIBQH*` Titan product of flybys Ta (T00A, 2004-10-26)
  through T19 (2006-10-09). That is 22 SAR imaging segments from 10 flybys,
  343,474,176 pixels, and 89,704,750 ZIP bytes to download.
- Sample sizes range from 2.7 M to 45.1 M pixels (shapes from 1408x1920 to
  16768x2688).

## Source

The USGS Astrogeology PDS Cassini bucket is anonymous S3:
`https://asc-pds-cassini.s3.us-west-2.amazonaws.com/RADAR/CORADR_vvvv/DATA/BIDR/<product>.ZIP`.
Each ZIP holds one DEFLATE member, `<product>.IMG`. That member is a PDS3
fixed-length file with an attached label, followed by the IMAGE object.

`sources.tsv` pins the following for each product:

- the volume
- the ZIP size and MD5 (the S3 ETag; all objects are single-part)
- the ZIP member CRC32 and compressed size
- the `.IMG` size and MD5 (the S3 ETag of the sibling uncompressed object)
- `RECORD_BYTES`, `FILE_RECORDS`, `LABEL_RECORDS`, `^IMAGE`, `LINES`,
  `LINE_SAMPLES`, the label `CHECKSUM`, and the start and stop times

`discover.sh` (metadata only: S3 listings, ~5 KB detached labels, and 1 KB ZIP
tails) produced it on 2026-10-05.

### Selection

`BIB` is the byte sigma0 product in dB. `Q` is oblique cylindrical, and `H` is
128 pixels/degree. The archive has 160 `BIBQH` products: 159 of Titan and one
of Enceladus (`BIBQH69S301_D232_E016S01_V02`, which has a different OFFSET of
-15.1 and is excluded). Every label asserts the same family constants:

- `TARGET_NAME = TITAN`
- `SAMPLE_TYPE = UNSIGNED_INTEGER`, `SAMPLE_BITS = 8`
- `SCALING_FACTOR = 1.0000012E-01`, `OFFSET = -2.0100010E+01`
- `MISSING_CONSTANT = 0`
- `MAP_RESOLUTION = 128.0<PIX/DEG>`
- `PRODUCER_INSTITUTION_NAME = "U.S.G.S. FLAGSTAFF"`

The full Titan H set is 3.68 GB of primary pixels, so the recipe takes a
chronological prefix of the mission: T00A through T19.

- All 22 products in the cut are `V03`, and each product base appears exactly
  once.
- Extending to T28 would give 37 products (805 MB). However, it adds several
  very large frames that are more than 90% fill (for example T20 S03, which is
  81 MB of IMG against 5 MB of ZIP).
- Excluded: the float products (F/D/S/U/X/E/T/N), the M/L backplanes, the
  other resolutions (B–G, I), and `RADAR/superseded/`.

## Conversion

1. `download.sh` fetches the ZIPs with resumable `curl -C -` and checks the
   size and MD5. It then runs `scripts/recipe.py validate`, which checks:
   - the ZIP holds exactly one DEFLATE member named `<product>.IMG`, with the
     pinned size and CRC32
   - the MD5 of the inflated IMG equals the pinned `.IMG` ETag
   - the attached label agrees with the pinned geometry and the family
     constants
   - `RECORD_BYTES*FILE_RECORDS` equals the IMG size
   - `FILE_RECORDS = LABEL_RECORDS + ceil(LINES*LINE_SAMPLES/RECORD_BYTES)`
   - the label `CHECKSUM` equals the sum of the image bytes (mod 2^32)
   - the image is not constant and not all-missing
2. `build.sh` inflates each ZIP and skips `(^IMAGE-1)*RECORD_BYTES` label
   bytes. `RECORD_BYTES` varies from 1024 to 4864 and `LABEL_RECORDS` from 1
   to 5 across products; one image line fills one record. It then copies
   `LINES*LINE_SAMPLES` bytes unchanged. No scaling, remapping, cropping,
   tiling or concatenation is applied. Output:
   `samples/<id>/cassini_radar_bidr_sigma0_db_u8/NN_<product>.u8`, plus
   `index/<id>/samples.jsonl` with the shape, product, flyby, segment, times,
   SHA-256 and DN statistics.
3. `verify.sh` independently re-derives every sample. It parses the ZIP local
   header by hand, inflates with raw zlib, reads the label with separate
   regexes, recomputes the checksums, and byte-compares the result with the
   emitted sample. It also checks the index and the manifest totals.

Physical value: `dB = DN * 0.10000012 - 20.10001`.

- DN 1 is the -20 dB clipping floor. Errata item 10 says all negative or
  below-0.01 sigma0 values are assigned to the minimum pixel value.
- No product contains a DN above 251, which is +5.0 dB.

## Missing values

DN 0 is the label `MISSING_CONSTANT`: pixels of the projected frame that lie
outside the SAR swath. These pixels are **preserved in place**. Swaths are
long, narrow strips inside an oblique cylindrical rectangle, so fill is a
large share of every image. Fill is real source structure and is not treated
as degenerate.

Realized build:
- DN 0 is 70.3% of all pixels, ranging from 56.3% (T7 S01) to 94.2%
  (T16 S03) per product.
- 102,140,599 pixels hold signal. The smallest per-product count is 182,572
  (T16 S03).
- Every product uses 246–251 distinct non-missing DN levels. The mean
  non-missing DN is 99–156 per product.
- DN 1 (the clip floor) is 4.0% of non-missing pixels. DN 251 (+5.0 dB, the
  top of the observed range) is 0.09%.
- All 22 sample SHA-256 values are distinct.

`verify.sh` rejects a product in any of these cases:
- it is constant or entirely missing
- it has fewer than 1% or fewer than 100,000 non-missing pixels
- it has fewer than 64 distinct non-missing DN levels

## License

USGS-produced data are in the U.S. public domain. Each label names
`PRODUCER_INSTITUTION_NAME = "U.S.G.S. FLAGSTAFF"`, and `ERRATA.TXT` item 8
says "The byte-valued backscatter images were produced by USGS." The USGS
Copyrights and Credits policy states: "USGS-authored or produced data and
information are considered to be in the U.S. public domain."

The data are also NASA SMD mission data openly released through PDS. The
accepted `nasa_pds_cassini_vims_qube_i16` relies on that same NASA SMD policy.

Neither policy page could be re-fetched while authoring (proxy HTTP 403), and
`download.sh` does not touch them. Cite the Cassini RADAR Team, USGS
Astrogeology (R. L. Kirk), the data set ID and the product IDs.

## Novelty and caveats

- **Novelty:** this is a new source. Locally, SAR imagery exists only at 16
  bits (`sentinel1_grd_measurement_u16`: Earth C-band GRD linear amplitude DN,
  not map-projected). There is no planetary or dB-quantized SAR image family
  at any width, and no 8-bit SAR imagery at all. The other Cassini recipe
  (`nasa_pds_cassini_vims_qube_i16`) covers a different instrument and
  different files. Magellan F-MIDR (Venus, S-band) is a queued candidate with
  a different scaling and target.
- **Fill:** images are fill-heavy. Compressibility is dominated by the swath
  mask plus 6–8-bit speckled backscatter.
- **Sample count:** 22 samples is near the soft target of about 20. The
  source offers more (159), but the 1 GB cap and fill-heavy later frames argue
  for the mission-chronological prefix.
- **Version mix:** later flybys mix product versions V02 and V03. This cut is
  all V03.
