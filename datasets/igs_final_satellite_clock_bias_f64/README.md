# IGS Final Combined GPS Satellite Clock Biases (30 s, 2024 H1) Float64

Estimated GPS satellite clock offsets from the International GNSS Service (IGS)
final combined clock product, emitted as one little-endian float64 series per
satellite-day.

## Source

- Product: `IGS0OPSFIN_2024DDD0000_01D_30S_CLK.CLK.gz`, the daily IGS final
  combined clock file at 30-second sampling (RINEX 3.00 clock format), for
  2024 day-of-year 001-182 (GPS weeks 2295-2321).
- Host: BKG IGS Global Data Center,
  <https://igs.bkg.bund.de/root_ftp/IGS/products/>, anonymous HTTPS
  (<https://igs.bkg.bund.de/access>).
- Pinning: `sources.tsv` lists all 182 files with GPS week, URL, exact size,
  Last-Modified and ETag. `discover.sh` regenerates it from the week listings
  and HEAD requests. The total is 519,688,708 bytes. BKG publishes no checksum
  files next to the products. All 182 sha256 values are now pinned in
  `sources.tsv`: 4 came from the authoring probes (days 001, 035, 120, 182)
  and 178 from the first validated download on 2026-10-05. That download
  passed the size, gzip CRC32/ISIZE and full semantic checks, and the 4
  pre-pinned digests matched. `download.sh`, build and verify all enforce
  the pins. Each run also writes the digests it observes to
  `downloads/<id>/download_plan.tsv`.
- Excluded products: the 05M CLK, SP3 orbits, ERP, summaries, rapid
  (`IGS0OPSRAP`), ultra-rapid (`IGS0OPSULT`) and MGEX products.

## License and attribution

The IGS Data and Product Disclaimer and Terms of Use (5 August 2020) is
linked as "Terms of Use" from igs.org:
<https://igs.org/wp-content/uploads/2020/09/IGS-Data-and-Product-Disclaimer-and-Terms-of-Use-200805.pdf>.
An identical copy sits on mgex.igs.org (sha256 `7b4e253c...8f8226`).

> The IGS products and station data are provided openly for the benefit of
> all scientific, educational, and commercial users. For 25 years, IGS data
> and products have been made openly available for use without restriction,
> and continue to be offered free of cost or obligation.

> By accessing data, products, and any other information from the IGS, users
> agree to appropriately cite and attribute these resources to providers and
> their sponsors, acknowledgment of IGS and its contributing organizations ...

Attribution: International GNSS Service. The combination is produced by the
IGS Analysis Center Coordinator (`IGSACC @ GA MIT`, Geoscience Australia and
MIT) from the analysis-center clocks named in each file header:

- days 001-070 and 072-083 (82 files): `esa gfz grg` (ESA/ESOC, GFZ Potsdam,
  CNES/CLS GRGS);
- day 071 (1 file): `gfz grg` only;
- days 084-182 (99 files): `cod esa gfz grg` (CODE/AIUB added).

Each index row carries its file's list in `contributing_acs`. Distribution is
by the BKG
Global Data Center. The citation IGS requests is Johnston, Riddell and
Hausler (2017), *The International GNSS Service*, Springer Handbook of GNSS,
pp. 967-982.

This is an open "use without restriction, with attribution" grant, not a
named SPDX license. The manifest records it as
`LicenseRef-IGS-Data-and-Product-Terms-of-Use-2020`.

## What is emitted

- Series `igs_final_gps_satellite_clock_bias_s_f64` (primary, float64, little
  endian).
- One sample per (day, GPS PRN):
  `samples/igs_final_satellite_clock_bias_f64/igs_final_gps_satellite_clock_bias_s_f64/2024_DDD_GNN.bin`.
- Values are the clock bias, in seconds, of one satellite relative to the IGS
  time scale (IGST, aligned to GPS time), in ascending 30-second epoch order.
  A complete day has 2,880 values (23,040 bytes).
- Natural record: one satellite's clock series inside one daily product file.
  The source file is epoch-major: every epoch interleaves around 31 satellite
  clocks and 100-200 station clocks. De-interleaving by PRN gives
  single-clock series and avoids mixing the per-satellite offsets, which range
  from about 1e-6 to 1e-3 s. Days are never concatenated.
- Not emitted: `AR` receiver/station clock records (including the `GPST`
  reference record), the bias sigma, and any further values (rate,
  acceleration and their sigmas).

## Conversion

1. gzip-decompress (CRC32 and ISIZE are checked) and find `END OF HEADER`.
   The header length varies from 128 to more than 200 lines with the station
   count.
2. Validate the header:
   - `RINEX VERSION / TYPE` is 3.00 `C`; `ANALYSIS CENTER` is `IGS`;
     `# / TYPES OF DATA` includes `AS`; `TIME SYSTEM ID`, when present, is
     `GPS`.
   - The comments state GPS-time alignment and IGST re-alignment, and the
     `GPS week: W Day: D MJD: M` comment matches the file's week, day and
     date.
   - `# OF SOLN SATS` equals the GPS-only `PRN LIST`.
3. Validate the data records:
   - Only `AR` and `AS` records occur.
   - Epochs lie on the 30 s lattice inside the file's day, are nondecreasing
     in file order, and strictly increase per PRN.
   - Each record holds 1-6 values. Values 3-6 sit on a continuation line,
     which the parser consumes.
   - Every value token is `[-]d.dddddddddddde±dd` (12 mantissa decimals), and
     the parsed float64 reproduces the token under `%.12e`.
   - The set of `AS` satellites equals the `PRN LIST`.
4. Take the first value of every `AS` record (the bias), group by PRN, and
   pack it as `<d`.

## Missing values and partial days

The source has no fill values. When the combination has no clock for a
satellite at some epoch, that epoch has no `AS` record. Samples contain only
the present epochs; nothing is interpolated or filled with sentinels. Each
index row carries `first_epoch_index`, `last_epoch_index`,
`missing_epoch_count` and `max_internal_gap_epochs`.
`filtered/<id>/ingest_stats.json` lists the exact missing epoch indices of
every gapped sample. Satellite-days with fewer than 1,000 epochs are excluded
and listed there too.

Realized: 5,615 of 5,688 satellite-days are complete (2,880 epochs). 73 have
gaps, with between 1,645 and 2,877 epochs. G13 accounts for 28 of them and
G21 for 12. No satellite-day fell below the 1,000-epoch threshold, so nothing
was excluded. The median sample has 2,880 values and the smallest has 1,645.

## Scope

All 182 files are used, giving 5,688 samples, 16,369,771 float64 values and
130,958,168 bytes.

- 32 distinct PRNs appear, with 29-32 satellites per day. G01 appears on 100
  days and G27 on 151 (they are absent from the PRN LIST on the other days).
  Every other PRN appears on 175-182 days.
- Values range from -6.96e-4 to 7.21e-4 s. Per-satellite magnitudes fall in
  decades 1e-7 (29 samples), 1e-6 (114), 1e-5 (595) and 1e-4 (4,950).
- Within a day a series is a near-linear drift, around 1e-11 to 1e-10 s per
  30 s, plus 7e-12 to 1e-10 s of step-to-step noise. In spot checks every
  complete sample had 2,880 distinct values.
- Consecutive days of the same PRN are continuous across midnight, but they
  stay separate samples.

## Validation

`verify.sh` runs `scripts/verify_igs_clk.py`, a separate fixed-column parser
that does not import the build module. It re-derives every sample and
byte-compares it with the emitted file. It also checks:

- every index field and the manifest totals;
- the floors and the size cap;
- that the sample directory holds exactly the indexed files;
- that each series is nonconstant, has unique content, and is not
  float32-exact.

`scripts/igs_clk.py selftest` runs as part of the build. It parses a synthetic
clock file containing a gap and a four-value record with a continuation line,
and checks that malformed variants are rejected.

## Nearest existing families

- `noaa_cors_rinex_observations_f64`: RINEX *observation* files from receivers
  (pseudorange, carrier phase, SNR). That is a different file type, producer
  and quantity.
- Staging `jpl_gps_time_series_f64`: station position time series.

No IGS product or clock-offset family exists locally, in the registry, or in
the downstream mirror.

## Reproduce

```bash
bash staging/igs_final_satellite_clock_bias_f64/download.sh   # ~520 MB, resumable
bash staging/igs_final_satellite_clock_bias_f64/build.sh
bash staging/igs_final_satellite_clock_bias_f64/verify.sh
```
