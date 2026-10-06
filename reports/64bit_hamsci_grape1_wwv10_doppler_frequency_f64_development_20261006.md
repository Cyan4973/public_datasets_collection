# HamSCI Grape V1 WWV 10 MHz received-frequency float64 development

## Outcome

Accepted `hamsci_grape1_wwv10_doppler_frequency_f64`. It holds the once-per-second
received-carrier-frequency estimates of the NIST WWV 10 MHz broadcast logged by
GPSDO-referenced Grape Gen 1 receivers of the HamSCI Personal Space Weather
Station network. One sample is one station-day file.

This is the first HF ionospheric-Doppler material in the local corpus and the
downstream corpus at any width. The nearest accepted 64-bit families are
`igs_final_satellite_clock_bias_f64` (GNSS satellite clock offsets) and
`jpl_gnssro_cosmic1_l1b_excess_phase_f64` (radio-occultation excess phase).
Both are related time-and-frequency or radio-propagation material, but they
come from different instruments and measure different quantities and scales.
Novelty kind: new source (and new quantity).

## Source and rights

- Source: Zenodo record 6590283 (concept 6584416), "Grape V1 Data: Frequency
  Estimation and Amplitudes of North American Time Standard Stations",
  K. Collins (HamSCI), published 2022-05-26. It holds 3,017 gzip CSV files
  totalling 1,992,244,203 bytes.
- Selected: all 920 `<date>T<HHMMSS>Z_<node>_G1_<grid>_FRQ_WWV10.csv.gz`
  files, 614,396,212 bytes. Each file's size and Zenodo md5 is pinned in
  `sources.tsv`.
- License: CC BY 4.0 at record level (`"license": {"id": "cc-by-4.0"}`,
  `access_right: open`). `download.sh` re-checks both on every run.
- The ESSD data paper, Collins et al. (2023), *ESSD* 15, 1403–1418, cites
  `doi:10.5281/zenodo.6590283` in its Code and data availability section.
- Version note: the record is `isObsoletedBy` 10.5281/zenodo.6622111, a
  repackaging into yearly ZIPs that also extends to 2024 and is also CC BY 4.0.
  The builder's CRC32 probe shows the overlapping files are content-identical.
  The pinned per-file record allows md5-verified per-file downloads.
- File headers contain volunteer callsigns, city names and coordinates. None
  are emitted. The index keeps only the public node id and the grid square
  already present in the file names.

## Shape and conversion

- Natural record: one station-day CSV file. A sample is that file's complete
  `Freq` column in row order.
- Freq is printed `%12.3f`: 10–11 significant digits on a 1 mHz lattice.
  `float(token)` gives the nearest binary64, written little-endian. No offset
  removal, rescaling, resampling, padding or interpolation.
- Width: float32 spacing near 1e7 is 1 Hz. 74,672,873 of 74,966,875 values
  (99.6%) are not float32-exact, so float64 is the honest width.
- Selection keeps one beacon (WWV10) and one receiver type (G1). It excludes
  WWV5, WWV2p5, CHU7, the S1 commercial receivers and 'Unknown' files.
- Whole files are excluded by rules pinned per file and re-derived
  independently in verify:
  - `time_order`, 9 files: backward clock resets after reboots.
  - `out_of_band` (|Freq − 10 MHz| > 100 Hz), 6 files: two N0000029 files
    labelled WWV10 that actually hold 5 MHz data, three re-tuned offset runs,
    and 3 rows at 20 MHz.
  - `too_short` (< 3,600 rows), 4 files.
- Gaps are not filled:
  - 73,139,962 steps of 1 s and 1,808,480 of 2 s. The logger skips about 2.4%
    of seconds, so a full day is about 84.4k rows.
  - 17,477 longer gaps and 53 repeated seconds.
  - 2,408,216 missing seconds in total, recorded per sample in the index.
- Known caveat: on 39 node-N00009 days between 2021-01-30 and 2021-05-03, the
  daily median lies more than 1 Hz from nominal (range −4.5..+7.9 Hz), with
  smooth hours-long offsets.
  - The paper gives typical variation as about ±1 Hz, so these offsets are
    probably instrumental rather than ionospheric.
  - The days are still genuine, non-degenerate receiver output on the same
    scale and lattice.
  - They are kept, documented in the README and manifest, and flagged per
    sample with `values_beyond_5hz` and `values_beyond_10hz`.

## Accepted output

- Pinned source files: 920. Kept: 903. Excluded: 17.
- Per node, kept / pinned:

| node | kept | pinned |
|---|---|---|
| N00009 | 292 | 294 |
| N0000007 | 280 | 284 |
| N0000014 | 132 | 134 |
| N0000015 | 110 | 113 |
| N00010 | 72 | 73 |
| N0000029 | 17 | 22 |

- Primary values: 74,966,875
- Primary bytes: 599,735,000
- Sample sizes: minimum 4,328, median 84,372, maximum 84,377 values.
  49 samples have fewer than 80k values and 3 have fewer than 10k.
- Value range: 9,999,989.721 to 10,000,010.400 Hz
- Span: 2020-07-21 to 2021-05-15

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py` passed with no warnings.
- **Verify:** I re-ran `verify.sh` and it passed in 18 s. It re-derived all
  920 statuses, round-tripped every stored double to its source token, and
  reported 0 unpinned statuses.
- **Build inputs:** `build.sh`, `grape_wwv10.py` and the verifier make no
  network calls. No credentials appear in any script.
- **Bytes, by node:** I read the first, middle and last sample of each of the
  6 nodes with `struct`:
  - Deviations are typically within ±1.5 Hz.
  - Each day has 600–3,700 distinct values.
  - Median |step| is 9–81 mHz, varying by station.
- **Bytes, whole set:** across all 903 samples:
  - Every value has binary64 exponent 1046.
  - The longest constant run is 7 values.
  - Only 117 values sit at the +10.4 Hz ceiling.
  - No two samples share a sha256.
- **Byte-exact check:** I independently re-parsed 6 random source files with
  a naive gzip and CSV split. All 6 are byte-exact against the stored samples.
- **N00009 caveat:** I characterised it with hourly medians and daily-median
  scans. Sustained offsets appear on 39 days, and only at N00009; the other
  five stations keep |daily median| ≤ 1.02 Hz.
- **Rights:** I fetched the Zenodo API record myself: cc-by-4.0, open access,
  3,017 files. On the ESSD article page, the data-availability section cites
  this exact DOI.
- **Novelty:** `novelty.py` over the record URL, the successor URLs and
  distinctive terms found no prior recipe, registry, ledger or downstream
  match for this source or quantity.
