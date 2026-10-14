# DWWSSN Sprengnether long-period vertical int16 development

## Outcome

Accepted `earthscope_dw_dwwssn_lp_seismogram_i16`: complete UTC station-days of
the long-period vertical channel (LHZ, 1 sps) of the USGS Albuquerque
Seismological Laboratory Digital World-Wide Standardized Seismograph Network
(FDSN network DW). Values are native 16-bit DWWSSN digitizer counts.

This family is terrestrial 1980s long-period seismology at the digitizer's
native full 16-bit range. It is distinct from the accepted
`earthscope_xa_apollo_pse_lunar_seismogram_i16`, which is lunar, 10-bit
digital units at 6.625 sps, decoded from Steim2. The modality (16-bit
seismometer counts) is already present, so novelty is new content in a known
modality. The zlsim byte-level breadth measurement is OK: the nearest family
is `covertype_uci:cov_col_05` at 0.1128, and Apollo is not the nearest.

## Source and rights

- Source: EarthScope (formerly IRIS DMC) fdsnws-dataselect 1, anonymous HTTPS.
  One GET per pinned station-day for
  `net=DW&sta={sta}&loc=--&cha=LHZ&start={day}T00:00:00&end={day+1}T00:00:00&nodata=404`.
- Plan: `plan.tsv`, 651 station-days over 14 stations, resolved once on
  2026-10-14 by `discover.sh`. It uses crc32-stratified candidate days and
  short-window presence probes, and takes 48 present days per station
  (BDF 41, LEM 34).
- Download: 651 miniSEED files, none empty, 120,172,136 bytes, plus the channel
  inventory, network StationXML and two license pages.
- License: U.S. Government work, public domain in the U.S.
  (`LicenseRef-US-Government-Public-Domain`):
  - The FDSN DW page says "Operated by Albuquerque Seismological
    Laboratory/USGS (ASL)".
  - The DataCite record for DOI 10.7914/SN/DW lists creator "Albuquerque
    Seismological Laboratory (ASL)/USGS" with no rights restriction.
  - The station service lists DW as `restrictedStatus="open"`.
  - The USGS data-licensing page states that federal works are "in the U.S.
    public domain, which means that anyone may use, copy, distribute, adapt,
    display and perform that work in the U.S. without permission", and
    prescribes CC0 for data wholly produced by USGS employees.
  - `download.sh` re-fetches and string-checks all three local license
    sources.
- Caveat: several stations were hosted by foreign institutions, but the
  operator and the DOI creator are ASL/USGS, and no separate terms are attached.
- Access caveat: EarthScope announced that downloads will require login from
  2026-12-15. This is the same caveat as the accepted Apollo XA recipe, and it
  is documented in the README and manifest.

## Shape and conversion

Each natural record is one station-day of DW.<sta>..LHZ.

Only inventory epochs with sensor "Sprengnether Series 201 S-5007-V
Seismometer", scale 5.0E8 and 1 sps are used. Excluded:
- the STS-1 epochs (counts of about ±60);
- the Geotech SL-210 stations;
- CMB's Guralp CMG3;
- the SCP epoch at 1.0E9 gain;
- the horizontals.

SEED data encoding 32 (DWWSSN) is a big-endian signed int16 per sample.
Values are decoded losslessly and written unchanged as little-endian int16,
with no scaling, filtering or instrument correction.

Records are sorted, exact duplicates dropped, and the chain must be contiguous
within 1 sample. A day is skipped whole if any of these hold:
- a gap, overlap or conflicting duplicate;
- fewer than 85,536 or more than 86,410 values;
- runs of 60 or more identical samples cover more than 1% of the day (fill,
  typically 128);
- more than 5% of samples are clipped;
- the mode covers more than 50% of the day;
- fewer than 64 distinct values;
- median |first difference| above 128.

The median-step rule was set after inspecting the built output. It removed
three HON 1984 malfunction days, and the README documents it.

## Accepted output

- Plan station-days: 651. Accepted: 512.
- Skipped: 103 fill, 25 gap, 3 overlap, 4 short, 1 mostly clipped,
  3 step noise.
- Stations: 14. Per station: AFI 42, ALQ 42, BDF 23, COL 44, GDH 41, HON 40,
  KBS 27, KEV 39, LEM 18, LON 38, SCP 38, SLR 41, TAU 43, TOL 36.
- Years: every year 1980-1993.
- Primary values: 44,236,869. Primary bytes: 88,473,738.
- Values per sample: 86,400 for 448 days, 86,399 for 10, and 86,401..86,405
  for 54. Median 86,400.
- Days with clipping: 28, with 9,533 clipped samples. The most-clipped is
  ALQ 1981-03-06 with 3,706.
- Aggregate decoded SHA-256:
  `98564fdbf9f86c2614d0825bc9893dcf5e28da62cde9dec2b165a85f506dcffb`

## Judge checks

- **Gate:** I re-ran `tools/autocollect/gate.py`. PASS, no warnings,
  widths=[16], median 86,400 values.
- **verify.sh:** I re-ran it. It passed in 69 s, including the synthetic
  encoder self-test and a byte-for-byte check against an independent
  fixed-layout record decoder. `build.sh` reads local files only.
- **Record structure:** I walked every record of every accepted day with
  `struct`. All records are 4096 bytes, quality M, zero time correction, and
  blockette 1000 encoding 32 big-endian. The first record starts 0.0-0.99 s
  after 00:00 and the last ends within 1 s after 24:00, so every sample is a
  true full UTC day. Five early-1980s days hold 67-220 shorter records
  (330 samples each) but still chain contiguously.
- **Value content:**
  - Background is centred near 0, with 88-99% of samples |v|<256 on typical
    days, median |step| 0-53 (median 5) and std 15-8,729 (median 360).
  - Most days carry a smooth step-calibration response of ±8.9k (ALQ, KBS) to
    ±17.4k (KEV), with the step-off about 400-450 s later. COL 1983-86 shows
    no calibration pulse.
  - At large amplitude the archive stores values with a fixed low byte
    (0x..FF or 0x..01). This is an upstream source property, and small values
    keep full resolution.
  - Isolated single-sample spikes total 11,275 (0.025%), mostly the value
    -511, concentrated in six AFI 1985-02..05 days (0.6-2.3% per day). These
    are genuine recorder artifacts, kept verbatim.
  - Max mode fraction is 0.173: SCP 1989-03-27 is a marginal near-dead day,
    hovering at 346-354 for most hours.
  - No duplicate sample hashes. The driver listed no fill warnings.
- **Homogeneity:** per-station series are stable across years (e.g. KEV std
  513-519 for 1981-1987). One sensor model, scale, rate, encoding and unit
  throughout.
- **Rights:** I read the local FDSN page, the network StationXML and the USGS
  page, and queried DataCite for the DOI myself. A grep found no credentials
  in any script, and there is no personal data.
- **Novelty:** I ran `novelty.py` with `--url` (dataselect, station, FDSN
  page), `--terms` (DWWSSN, Sprengnether, net=DW, DOI), `--vocabulary` and
  `--type/--instrument/--archive`. No DW or DWWSSN material exists locally,
  in the registry, in the ledger or downstream. The only 16-bit seismometer
  family is the lunar Apollo set, and neither downstream 16-bit tree holds any
  seismic families.
