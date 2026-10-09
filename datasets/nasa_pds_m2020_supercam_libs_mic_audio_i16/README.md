# Mars 2020 SuperCam Microphone Raw Audio (LIBS bursts, 100 kHz, gain 2), uint16

Raw acoustic recordings made on Mars by the SuperCam microphone on the
Perseverance rover's remote-sensing mast, taken from the NASA PDS Geosciences
Node SuperCam bundle (`urn:nasa:pds:mars2020_supercam`, collection
`data_raw_audio` v16.0). Each sample is the complete SOUND table of one raw
audio FITS product: 174,000 microphone ADC codes at 100 kHz, recorded during a
30-shot LIBS (laser-induced breakdown spectroscopy) burst. The recordings hold
laser-spark shock transients plus Martian wind and ambient noise.

- 634 products (one sample each), sols 86-1857, 465 distinct sols
- 110,316,000 uint16 values, 220,632,000 bytes
- download: 396,984,960 bytes (634 whole FITS files)

## Source and rights

- Collection: <https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_supercam/data_raw_audio/>
- Citation: Wiens, R. C.; Maurice, S. A. (2021), Mars 2020 SuperCam Raw Audio
  Data Collection, NASA PDS Geosciences Node.
- Rights: NASA SMD open scientific data policy
  (<https://science.nasa.gov/researchers/science-data/science-information-policy/>):
  "information produced from SMD-funded scientific research activities be made
  publicly available". This is the same basis as the accepted
  `nasa_pds_mastcamz_raw_i16` and `nasa_pds_sharad_edr_raw_echo_i8` recipes.
  The bundle has no explicit CC/PD licence file and no stated restriction.
  SuperCam was built by LANL and CNES/IRAP.

## Selection (`discover.sh`, metadata only)

1. Read the sizes of all 13,420 raw-audio FITS products from the 1,233 sol
   directory listings. Candidates are the 12,220 files under 1 MB, the short
   LIBS recordings; long recordings are 2-23 MB. They are sorted by file name,
   which orders them by sol and spacecraft clock.
2. Split the candidates into 800 equal consecutive windows. In each window,
   range-probe candidates in order and keep the first product that matches the
   configuration below. Two probes are made per product: the 17,280-byte primary
   header, and the 2,880-byte block at `file_bytes - 351,360` where the final
   SOUND HDU header must sit.
   - Primary header: `MIC_SAMP=100000` (Hz), `MIC_DOWN=F` (not downsampled),
     `MIC_SAMC=21`, `MIC_GAIN=2`, `MIC_DURA=1`, `HSS_NUMW=174000`,
     `LIBS_MIC=T`, `LASDNS00=30` (30 shots), `SCMDTYPE=9`.
   - SOUND header: BINTABLE, `NAXIS1=2`, `NAXIS2=174000`, `TFORM1='I'`,
     `TZERO1=32768`.
3. Resolved: 634 windows. The other 166 windows held only gain-1, gain-3,
   294,000-word or too-small products. Gain is set per sequence, so gain-2
   products come in runs. The pinned product MD5s come from the bundle MD5
   manifest, and every LID and major version was checked against the
   collection inventory.

Why gain 2 only: the microphone gain setting changes the amplitude scale.
Gain-1 recordings have a standard deviation of ~8-11 counts and ~200-270
distinct values; gain-2 recordings have ~25-140 counts and ~350-1,700
distinct values. Mixing gains would mix two scales. Gain 2 is the most common
setting (58% of a 1-in-40 header sample of 30-shot products) and occurs from
sol 86 to sol 1857. The sampling rate is the same (100 kHz) across all 306
products in that sample.

## Conversion

The FITS file holds, in order: primary header, ODL LABEL, TIMELINE, MU_SOH,
BU_SOH, LASERDATA, SOUND. Build walks the 2,880-byte header blocks, requires
exactly one SOUND HDU, placed last and at the pinned offset, and reads its
348,000 bytes of big-endian int16. It writes `stored + 32768` as little-endian
uint16.

FITS uses `TFORM 'I'` with `TZERO 32768` as its standard way to store unsigned
16-bit data. The PDS4 label calls it SignedMSB2 with `value_offset` 32768. The
physical value is therefore the instrument's uint16 ADC code: centred near
1,880, with observed values from 0 to ~3,050. Emitting the stored signed codes
instead would keep a FITS offset artifact (values near -30,900). The dataset ID
keeps the candidate's `i16` suffix, but the series is `uint16`.

There is no fill value, and every row is emitted. As a quality policy, a
recording with fewer than 64 distinct values, or with one value above 50% of
its samples, is dropped and logged as a dead or stuck microphone. `verify.sh`
re-derives every sample with a separate parser. It finds the SOUND header by
scanning backwards and decodes by flipping the sign bit at byte level. It then
byte-compares the result against the samples and checks the index fields, the
quality policy and the manifest totals.

## Notes and caveats

- Time structure: in the inspected products, shock transients recur every
  ~6,000 samples (60 ms), even though the laser fires at a few Hz. This fits
  the instrument storing one short window per shot, back to back. I inferred
  this from the data and did not confirm it in the SIS. Each FITS product is
  one natural record, and nothing is cut or concatenated.
- The signal is quiet. Between shots it is low-level noise; for gain 2,
  order-0 entropy is ~6-8.5 bits per sample and the dominant value is ~1-5%.
- I picked 634 products, roughly a tenth of the gain-2 population in the
  30-shot class. My estimate of that population is about 6,700 products, or
  ~2.3 GB of SOUND data, which is past the 1 GB cap, so a spread subset is
  taken.
- The PDS4 XML labels (~146 KB each) are not downloaded, because every
  selection keyword is in the FITS primary header.

## Files

`discover.sh` (metadata-only resolution) -> `sources.tsv`; `download.sh`,
`build.sh`, `verify.sh`; `scripts/m2020mic.py` (discovery and build) and
`scripts/verify_mic.py` (independent verifier).
