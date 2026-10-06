# USAF RSTN Sagamore Hill Solar Radio Spectrograph (SRS) daily dynamic spectra, uint8 (2024)

This recipe collects native 8-bit swept-frequency solar radio spectra from the
Solar Radio Spectrograph of the US Air Force Radio Solar Telescope Network
(RSTN) at Sagamore Hill, Massachusetts (RSTN site 5). NOAA NCEI archives the
data. Each natural record is one station-day file, the day's full dynamic
spectrum. The recipe splits each day into its two analyser bands. Each band
becomes one sweeps x 401 uint8 matrix:

| series | role | content |
|---|---|---|
| `srs_band_a_25_75mhz_u8` | primary | band A analyser levels, 25.000-75.000 MHz, 401 linearly spaced channels |
| `srs_band_b_75_180mhz_u8` | primary | band B analyser levels, 75.000-180.000 MHz, 401 linearly spaced channels |
| `srs_sweep_start_utc_seconds_u32` | auxiliary | sweep start time, in seconds since 00:00 UT of the file date |

Values are the spectrum-analyser output level, a relative logarithmic power
from 0 to 255 with no absolute calibration (NCEI `Srsdispl.doc`). The recipe
copies them verbatim.

## Source and rights

- Archive: <https://www.ngdc.noaa.gov/stp/space-weather/solar-data/solar-features/solar-radio/rstn-spectral/sagamore-hill/2024/>
  (Apache index, one `kYYMMDD.srs.gz` per local observing day).
- Format documentation: `rstn-spectral/documentation/Srsdispl.doc`, section
  2.2 "SRS Data Records".
- Rights: the NCEI ISO 19115 record
  `gov.noaa.ngdc.stp.solar:solar-features_solar-features_solar-radio`
  ("Solar Radio") covers "RSTN solar spectral measurements". It states
  "Access Constraints: None Use Constraints: None", followed by a NOAA
  liability disclaimer. NCEI's collection readme
  (`solar-radio/documentation/readme_solar-features_solar-radio.pdf`) lists
  "Sagamore Hill (USAF Radio Solar Telescope Network)". The data are therefore
  US Government works (17 U.S.C. 105). `download.sh` re-fetches the ISO record
  on every run and fails if those phrases disappear.
- The recipe uses Sagamore Hill only. It excludes Learmonth, which is jointly
  operated with the Australian Bureau of Meteorology, and the other stations,
  so that all data share one receiver scale.

## Selection (`discover.sh`, pinned in `sources.tsv`)

The requested days are the 1st, 11th and 21st of each month of 2024. For each
requested day, the recipe takes the first day among d..d+9 (same month) whose
file is listed and passes all of these checks:

- the gzip trailer ISIZE is a multiple of 826, and the file has at least
  5,000 records;
- every record in a 32 KiB head range has site 5, 2 bands, band descriptors
  (25,75,401,20,0) and (75,180,401,20,0), and the file's own date.

Discovery uses only listings and two small range requests per candidate. Two
days were substituted:

- 2024-07-01 is a 297-record outage file and 2024-07-02 is not archived, so
  2024-07-03 is used instead.
- 2024-08-21 and 2024-08-22 are not archived, so 2024-08-23 is used. It is a
  late-start day (first sweep 15:49:27 UT, 9,076 records).

For every file, `sources.tsv` pins the size, Last-Modified, the gzip CRC32 and
ISIZE from the trailer (this pins the decompressed content), the record count
and the first sweep time. The whole-file SHA-256 values come from the first
driver download on 2026-10-06, which validated all 36 files record by record.
They are pinned in `sources.tsv` and enforced by download, build and verify.

## Record layout and conversion

Each record is 826 bytes, and records have no separators:

- bytes 0-5: year (2 digits), month, day, hour, minute and second (UT);
- byte 6: site (5);
- byte 7: number of bands (2);
- bytes 8-15 and 16-23: big-endian `>HHHBB` band descriptors (start MHz, end
  MHz, byte count, analyser reference level, attenuation in dB);
- bytes 24-424: band A levels;
- bytes 425-825: band B levels.

`build.sh` decompresses each pinned file and checks **every** record header:

- site 5 and 2 bands;
- band A descriptor exactly (25, 75, 401, 20, 0) and band B exactly
  (75, 180, 401, 20, 0), so the reference level and attenuation, and with them
  the DN scale, never change;
- header date equal to the file date or the next UT day;
- valid hour, minute and second.

Any violation is fatal. The build never uses part of a file and never mixes
scales. Bytes `[24:425)` and `[425:826)` of each record are written in file
order as row-major (sweeps x 401) uint8 matrices. Output files are named:

- `samples/<id>/srs_band_a_25_75mhz_u8/sagamore_hill_YYYYMMDD_band_a.u8`
- `samples/<id>/srs_band_b_75_180mhz_u8/sagamore_hill_YYYYMMDD_band_b.u8`
- `samples/<id>/srs_sweep_start_utc_seconds_u32/sagamore_hill_YYYYMMDD_sweep_start_utc_s.u32`

The index rows carry `sample_shape`, frequency edges, reference level,
attenuation, source file, source SHA-256, sample SHA-256, and value
statistics.

## Realized scope (pinned)

- 36 station-days (2024).
- 504,393 sweeps, between 9,076 and 17,942 per day, tracking day length.
- 72 primary samples totalling 404,523,186 bytes (202,261,593 per band). The
  median primary sample is 5,547,634.5 values.
- The auxiliary series is 2,017,572 bytes.
- Download: 277,776,099 bytes of gzip plus a 64 KB ISO metadata record.
- Per band sample:
  - 178-256 distinct codes;
  - mode share at most 7.83%;
  - code 0 at most 0.0134% and code 255 at most 0.0167%;
  - daily mean 33.2-51.0 DN for band A and 61.2-71.4 DN for band B.

## Verification

`verify.sh` does not share code with the build. It:

- re-decodes each file with a streaming zlib decoder;
- unpacks every record with a single `struct` format and re-checks every
  header;
- re-derives both band planes and the time series, and compares them byte for
  byte with the built samples;
- checks index fields, sample hashes and the manifest totals.

It rejects degenerate samples, defined as any of:

- fewer than 64 distinct codes;
- a mode share above 25%;
- codes 0 and 255 together above 1%;
- fewer than 99% of channels varying over the day;
- flat sweeps above 0.1%;
- verbatim-repeated consecutive sweeps above 2%.

On the real build, `verify.sh` passed for all 36 days (72 primary samples).
Before the download, the scripts were self-tested on 35 synthetic SRS days
plus one real day
(2024-12-11, fetched as a probe), using file:// URLs to exercise resume. The
tests included one synthetic day that crosses midnight UT, and 15 corrupted or
mismatched variants (mid-file site, band count, reference level, attenuation,
date and time changes, truncation, a short day, and gzip CRC, size, SHA and pin
mismatches), all rejected.

## Caveats

- The cadence is nominally 3 s. Realized steps are mostly 3 s, with
  occasional 2 s, 4 s and 5 s steps: per day, 0-12 steps of 4 s and 1-9 of
  2 s.
- There are 19 intra-day observing gaps longer than 5 s, on 11 of the 36 days.
  They range from 12 s to 4,124 s; the longest is on 2024-09-11.
- Timestamps strictly increase on every day. The cadence is not enforced; the
  auxiliary time series keeps the real sweep times.
- On 33 of 36 days the file begins with a fixed start-up sequence of about 35
  records (records about 19-59, roughly 1.5 min after the first sweep):
  - levels repeat in groups of four identical sweeps, giving 24-30 verbatim
    repeats per day;
  - the block holds every code-0 value of the collection except two sweeps on
    2024-03-01 (records 6308-6309);
  - 2024-06-21, 2024-08-23 and 2024-10-11 lack the sequence.

  It is part of the station-day record and is kept verbatim, without trimming.
  Verify caps repeated sweeps at 2% per sample; the realized share is at most
  0.24%.
- The collection contains one flat sweep: an all-255 (saturated) band B sweep
  on 2024-01-11 at 13:45:29 UT.
- Some HTTP Last-Modified values precede the end of the observing day; for
  example, 2024-01-01 reports 16:10:54 GMT. The archive's timestamps appear to
  be in a local zone. They are informational only, and the content is pinned
  by the gzip trailer.
- Band A and band B are different analysers, with daily means of 33-51 DN and
  61-71 DN. They are kept as two series of one family, not concatenated.
- Related corpus material: `csiro_parkes_uwl_search_mode_u8` is a pulsar
  search-mode filterbank (Parkes UWL, 0.7-4 GHz, 128 us, one 0.5 s
  sub-integration per sample). This recipe is a solar swept-frequency
  spectrograph at 25-180 MHz with 3 s sweeps over whole days. The candidate
  `ecallisto_solar_radio_spectrogram_u8` was screened out on rights only.
