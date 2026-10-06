# IGS final combined GPS satellite clock-bias float64 development

## Outcome

Accepted `igs_final_satellite_clock_bias_f64`. The recipe uses the 182 daily IGS final combined 30-second RINEX 3.00 clock products for 2024 day-of-year 001-182 (GPS weeks 2295-2321).

The family adds a new quantity: GNSS satellite clock offsets as estimated by the IGS clock combination. The nearest local family is `noaa_cors_rinex_observations_f64`. It holds receiver RINEX observation files (pseudorange, carrier phase, SNR), which are a different file type, producer and quantity. No IGS product, satellite-clock or orbit family exists in `datasets/`, staging, the registry, the pipeline ledger or the downstream mirror.

## Source and rights

- Source: BKG IGS Global Data Center, `https://igs.bkg.bund.de/root_ftp/IGS/products/<week>/IGS0OPSFIN_2024DDD0000_01D_30S_CLK.CLK.gz`, anonymous HTTPS.
- Files: 182, 519,688,708 compressed bytes.
- Pinning: `sources.tsv` lists the doy, GPS week, URL, size, Last-Modified, ETag and sha256 for every file. All 182 sha256 values are pinned.
  - 4 come from authoring probes and were matched by the driver download.
  - 178 are trust-on-first-download, because BKG publishes no checksum files. That download passed the size, gzip CRC32/ISIZE and full semantic validation.
  - download.sh, build and verify all enforce the pins.
- License: IGS Data and Product Disclaimer and Terms of Use (5 August 2020), `https://igs.org/wp-content/uploads/2020/09/IGS-Data-and-Product-Disclaimer-and-Terms-of-Use-200805.pdf`, sha256 `7b4e253c24073af930c38ac65b30ae5208850c4a5681a0e2c6bbf388e72f8226`. Recorded as `LicenseRef-IGS-Data-and-Product-Terms-of-Use-2020`.
  - The text names "satellite and station clock biases" among IGS products.
  - It states they are "provided openly for the benefit of all scientific, educational, and commercial users ... made openly available for use without restriction".
  - It requires citation and attribution of IGS and contributing organizations. The manifest carries this: IGS, IGSACC (GA/MIT), BKG, and the ACs esa, gfz, grg and cod per file header, plus Johnston, Riddell and Hausler (2017).

## Shape and conversion

Each daily file is epoch-major and interleaves about 31 satellite (`AS`) clocks with 46-200 station (`AR`) clocks. A sample is one GPS satellite's clock series within one daily file, in ascending 30-s epoch order. That gives up to 2,880 values per sample, and days are never concatenated. Per-file samples would interleave satellites whose offsets differ by orders of magnitude, so the per-satellite split is the cleaner natural record.

Conversion steps:
1. gzip-decompress.
2. Validate the header:
   - RINEX 3.00 type C, ANALYSIS CENTER IGS, TYPES OF DATA include AS.
   - The IGST/GPS-time alignment comments are present.
   - The GPS week/day/MJD comment equals the file identity.
   - # OF SOLN SATS equals the GPS-only PRN LIST, which equals the AS satellite set.
3. Validate the records:
   - Only AR and AS record types occur.
   - Epochs sit on the 30-s lattice within the day, are nondecreasing in file order and strictly increase per PRN.
   - Continuation lines are consumed.
4. Keep the first AS value (the bias). Every token must match the 12-decimal mantissa pattern and round-trip under `%.12e`.
5. Pack as `<d`.

AR clocks, sigmas and rate terms are dropped. No scaling, differencing or detrending is applied.

Missing epochs are omitted, never filled. The index carries first/last epoch, missing_epoch_count and max_internal_gap_epochs. `ingest_stats.json` lists the exact missing epoch indices. The 1,000-epoch exclusion rule removed nothing.

## Accepted output

- Source files validated: 182 of 182
- Primary samples: 5,688. 32 PRNs with 29-32 per day; G01 is present on 100 days and G27 on 151.
- Complete samples (2,880 values): 5,615
- Gapped samples: 73 (1,645-2,877 values; G13 accounts for 28, G21 for 12)
- Primary values: 16,369,771
- Primary bytes: 130,958,168
- Minimum sample: 1,645 values
- Median sample: 2,880 values
- Maximum sample: 2,880 values
- Value range: -6.962649226534e-04 to 7.208930134833e-04 s
- Contributing-AC sets per sample: esa gfz grg 2,579; gfz grg (day 071) 32; cod esa gfz grg (from day 084) 3,077
- Aggregate decoded SHA-256 (samples concatenated in index order): `b91fac157a6f57f04e9c6e9de0bde322dbd58ec7826994cdf0f9dae44a11f882`

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/igs_final_satellite_clock_bias_f64` returned PASS with no warnings.
- **Verify:** I ran `bash staging/igs_final_satellite_clock_bias_f64/verify.sh`. It returned verify=ok (files=182, samples=5688, values=16369771, bytes=130958168, gapped=73, excluded_short=0). The verifier is an independent fixed-column parser that byte-compares every sample.
- **Build is local:** build.sh, verify.sh and both Python scripts contain no network calls. The driver's download log shows check_downloads=ok, 182 files, 519,688,708 bytes.
- **Independent raw parse:** I parsed the raw files for doy 071 (gfz/grg-only day, with gaps) and doy 140 with a whitespace-split parser of my own. The G05, G13 and G21 sequences equal the emitted samples exactly; for example, G21 on day 071 has 2,144 values. Every record in both files has nvalues=2.
- **Value spot checks:** six random samples show magnitudes of 2.4e-6 to 7.1e-4 s, drift of -6.6e-12 to -2.8e-10 s per 30 s, second-difference sd of 9e-12 to 1.4e-10 s, 2,880 distinct values each, and no float32-exact values.
- **Full-corpus scan of all 5,688 samples:**
  - The most frequent repeated first difference covers at most 0.17% of a sample, so nothing is interpolated.
  - 22 samples contain one duplicate value, which chance explains at 13 significant digits.
  - The largest step is a 1.001e-6 s clock adjustment in 2024_146_G07, present in the source.
  - Second-difference noise has a median of 1.4e-11 s against a decimal resolution of about 1e-16 s, so there are about 17 bits of genuine noise per value.
  - Day boundaries are continuous but not duplicated (G26, day 013 to day 014).
- **Rights:** I fetched the IGS terms PDF myself; its sha256 matches the manifest, and I read the Background, Attribution and Terms of Use sections. igs.org links this PDF as "Terms of Use". The BKG GDC access page documents anonymous HTTPS with no additional terms. The scripts contain no credentials and the data contain no personal information.
- **Novelty:** `python3 tools/autocollect/novelty.py --url https://igs.bkg.bund.de/root_ftp/IGS/products/ --terms igs clock rinex gnss satellite IGS0OPSFIN cddis bkg sp3` found no URL match outside this staging recipe and no IGS clock or product family. The only term hits are NOAA CORS observation families and unrelated tokens.
- **Accepted caveats:**
  - Series are smooth drift plus picosecond-level estimation noise.
  - Per-satellite magnitudes span four decades, but in one unit and one process.
  - The download is about 4x the kept output. The kept signal is large in absolute terms, and no leaner anonymous 30-s source exists.
  - 178 checksums are trust-on-first-download because the host publishes none.
