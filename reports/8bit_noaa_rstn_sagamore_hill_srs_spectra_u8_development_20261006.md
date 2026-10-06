# USAF RSTN Sagamore Hill SRS dynamic spectra uint8 development

## Outcome

Accepted `noaa_rstn_sagamore_hill_srs_spectra_u8`, a native 8-bit solar radio
dynamic-spectrum family. It comes from the US Air Force Radio Solar Telescope
Network (RSTN) Solar Radio Spectrograph at Sagamore Hill, Massachusetts (site
5), archived by NOAA NCEI.

This family is distinct from the accepted `csiro_parkes_uwl_search_mode_u8`:

- **Parkes:** an L-band (0.7-4 GHz) pulsar search-mode filterbank of digital
  coherency products at 128 us resolution.
- **This recipe:** the logarithmic output level of two swept HP8591E spectrum
  analysers at 25-180 MHz, one sweep every 3 s through whole observing days.
  It is a different instrument, signal, generation process and source.

It is the second 8-bit radio dynamic-spectrum family in this collection
effort. Novelty kind: `new_source`.

## Source and rights

- Archive:
  `https://www.ngdc.noaa.gov/stp/space-weather/solar-data/solar-features/solar-radio/rstn-spectral/sagamore-hill/2024/{MM}/k724MMDD.srs.gz`
- Day files: 36, pinned in `sources.tsv` by:
  - size
  - Last-Modified
  - gzip CRC32/ISIZE
  - record count
  - first sweep time
  - SHA-256 (36 unique)
- Downloaded gzip bytes: 277,776,099. Decompressed bytes: 416,628,618.
- Format: NCEI `rstn-spectral/documentation/Srsdispl.doc`, section 2.2 "SRS
  Data Records". Each 826-byte record is a 24-byte header followed by 401
  band A and 401 band B bytes, each "a binary number from 0 to 255
  representing the output level of each spectrum analyser at that
  frequency", on a logarithmic scale.
- Rights:
  - The NCEI ISO 19115 record
    `gov.noaa.ngdc.stp.solar:solar-features_solar-features_solar-radio`
    covers "RSTN solar spectral measurements". It states "Access
    Constraints: None Use Constraints: None", with only a liability
    disclaimer.
  - The NCEI readme `readme_solar-features_solar-radio.pdf` lists "USAF
    Radio Solar Telescope Network - SRS ... Sagamore Hill (2004-Present)".
    The data are therefore US Government works
    (`LicenseRef-US-Government-Public-Domain`, as in the accepted
    `noaa_coops_*`, `earthquake_usgs` and `naif_*` recipes).
  - `download.sh` re-checks the ISO phrases on every run.
  - Learmonth, which is jointly operated with the Australian BOM, and the
    other stations are excluded.

## Shape and conversion

**Selection.** The requested days are the 1st, 11th and 21st of each month of
2024. Each takes the first acceptable day among d..d+9 in the same month. Two
days were substituted:

- 2024-07-01 is a 297-record outage and 07-02 is not archived, so 07-03 is
  used.
- 2024-08-21/22 are not archived, so 08-23 is used. It is a late-start day
  with 9,076 records.

**Conversion.** Each natural record is one station-day file:

1. Gunzip the file.
2. Split it into 826-byte records.
3. Validate every header: site 5, 2 bands, band descriptors exactly
   (25,75,401,20,0)/(75,180,401,20,0), and a date equal to the file date or
   the next UT day. Any violation is fatal.
4. Copy bytes `[24:425)` and `[425:826)` verbatim as row-major
   sweeps x 401 uint8 matrices, one per band.

An auxiliary little-endian uint32 series carries each sweep's start time in
seconds from 00 UT of the file date. Nothing is scaled, masked, trimmed or
concatenated across days.

**Disclosed features:**

- On 33 of 36 days there is a ~35-record start-up calibration staircase. It
  produces 24-30 verbatim-repeated sweeps per day, at most 0.24% of a sample,
  and holds nearly all code-0 values.
- 19 intra-day observing gaps longer than 5 s on 11 days.
- One flat (all-255) band B sweep in the whole collection.

## Accepted output

- Station-days: 36. Sweeps: 504,393, between 9,076 and 17,942 per day
  (median 13,834.5).
- Primary samples: 72 (36 per band).
- Primary values and bytes: 404,523,186 (202,261,593 per band).
- Sample size: 3,639,476 to 7,194,742 values. Median primary sample:
  5,547,634.5 values.
- Band A (25-75 MHz):
  - 178-256 distinct codes;
  - mode share at most 4.50%;
  - daily mean 33.2-51.0 DN.
- Band B (75-180 MHz):
  - 225-256 distinct codes;
  - mode share at most 7.82%;
  - daily mean 61.2-71.4 DN.
- Code 0 at most 0.0134% and code 255 at most 0.0167% per sample.
- Auxiliary sweep-time series: 36 samples, 2,017,572 bytes.

## Judge checks

- **Gate.** `python3 tools/autocollect/gate.py staging/noaa_rstn_sagamore_hill_srs_spectra_u8`
  gave PASS with no warnings: 72 samples, 404,523,186 values, median
  5,547,634.5, width 8.
- **Verify.** I ran `bash staging/noaa_rstn_sagamore_hill_srs_spectra_u8/verify.sh`
  myself and got verify OK (about 61 s). The verifier does not import the
  build helper. It re-decodes every file and re-derives every sample byte for
  byte.
- **Build is local-only.** grep found no curl, urllib, socket or URLs in
  `build.sh`, `verify.sh` or the Python helpers, and no credential strings in
  any script.
- **Independent decode.** My own gzip+`struct` decode of 7 days (01-01,
  03-11, 05-21, 08-01, 09-01, 10-11, 12-21) showed:
  - one header configuration per file;
  - header dates match the file date;
  - band planes equal record bytes for every sweep;
  - strictly increasing times, about 99.9% at a 3 s step.
- **Bytes.**
  - Spectral profiles are physically plausible: strong low-frequency noise
    in band A, higher in winter, and a stable band B passband with
    interference lines. Sweep means drift through the day.
  - Zero-order entropy is 5.5-6.3 bits, time-delta entropy 3.4-4.3 bits, and
    the zlib-6 ratio is 1.48-1.80.
  - All 108 sample SHA-256 values are unique.
  - Duplicate sweeps appear only inside the start-up calibration staircase,
    at records about 20-54.
- **Format.** I fetched NCEI `Srsdispl.doc`: section 2.2 layout, frequency
  formulas and the logarithmic 0-255 scale all match the recipe.
- **Rights.** I read the ISO XML rights text and the NCEI readme PDF that
  lists Sagamore Hill as a USAF RSTN SRS station.
- **Novelty.** `novelty.py` found no other RSTN or NGDC solar-radio recipe,
  registry row or downstream entry. Term hits were only Parkes (filterbank),
  IRIS (FUV CCD) and the rights-screened e-CALLISTO.
- **Claimed totals.** Sweeps, bytes per band, auxiliary bytes and gz bytes
  all reproduce exactly from `sources.tsv` and the index.
