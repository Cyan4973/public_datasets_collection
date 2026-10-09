# Apollo PSE long-period vertical (MHZ) lunar seismograms, int16

Station-days of the long-period vertical channel of the Apollo 12, 14, 15 and
16 ALSEP Passive Seismic Experiment (PSE) seismometers on the Moon, 1971-1977.
The data come from the restored archive of Nunn et al. (2022), which EarthScope
serves as FDSN network **XA (1969-1977)** (DOI 10.7914/SN/XA_1969).

- Channel `MHZ`, location `00`: long-period vertical in peaked response mode,
  nominal 6.625 samples/s on a constant sampling interval.
- Values are native 10-bit telemetry digital units (0..1023). The archive
  stores each missing sample inline as `-1`.
- One sample is one UTC station-day of about 572,400 values (~1.14 MB as
  little-endian int16).

## Scope

`plan.tsv` lists 119 pinned station-days: S12 36, S14 17, S15 36, S16 30,
spread over 1971-1977. It was resolved once by `discover.sh` /
`scripts/discover.py`:

1. Take 8 crc32-derived candidate days per station-year.
2. Probe three 10-minute windows per candidate in POST requests to
   fdsnws-dataselect.
3. Keep a candidate when every window holds at least 95% of its samples and at
   most 20% of the pooled samples are `-1`.
4. Take up to 36 days per station, round-robin over years.

Of 216 candidates, 126 were present. Coverage has two known holes, both from
the archive itself:

- S14 location `00` has little data in 1972-1975.
- S12, S15 and S16 have no location-`00` data during the flat-mode period
  (1975-06-28..1977-03-27). That period is archived under location `01`.

### Realized output (download of 2026-10-09)

106 of the 119 plan days were emitted: 60,666,177 values, 121,332,354 bytes.

| Station | Days |
|---------|------|
| S12     | 30   |
| S14     | 16   |
| S15     | 31   |
| S16     | 29   |

Every year 1971-1977 is covered. 13 days were skipped:

- 5 degenerate (fewer than 16 distinct valid levels)
- 4 short (less than 99% of a day)
- 2 with gaps between records (2.6 and 77.7 samples)
- 2 with more than 20% `-1`

Per-sample statistics, as median (range):

- distinct values: 166 (18..878)
- mode fraction: 0.49 (0.07..0.92)
- `-1` count: 1,751 (2..109,059)

Two days carry many full-scale 1023 words, which the policy keeps as archive
content:

- S14 1977-04-03: 41,438 words (7%)
- S16 1977-05-08: 1,384 words

Nine quiet days have a single value in more than 80% of their samples (a DC
level with little signal).

## Exclusions (homogeneity)

- Location `01`: flat response mode. It is a different transfer function, so
  it is not requested.
- S11 (Apollo 11): 1969 only, a different short-lived instrument deployment.
- SHZ (short-period, 53 sps), the horizontals MH1/MH2/MHE/MHN, and ATT (the
  timing channel).
- Requests are always pinned to stations S12/S14/S15/S16 and days inside
  1971-1977, and every record's `XA.<sta>.00.MHZ` identity is checked, because
  the XA network code is reused by later temporary networks.

The archive authors warn that short periods may carry the wrong peaked/flat
location label. The recipe trusts the archive's labels.

## Decode and policy

`scripts/mseed.py` is a pure-stdlib miniSEED 2 reader adapted from the
accepted `earthscope_pb_borehole_strain_counts_i32` recipe:

- Reads the BTIME start time and applies blockettes 1000 and 1001.
- Decodes Steim2 and checks every record's X0/Xn integration constants.

`scripts/selftest_steim2.py` checks the decoder against an independent
synthetic Steim2 encoder before every validate, build and verify run. The test
covers every Steim2 sub-format, rejection of a corrupted Xn and of short
frames, and chain assembly. On 8 real probe days the decoder was
sample-identical to the PB model decoder.

A station-day is emitted only if all of these hold:

- Its records chain contiguously: sorted by start time, exact duplicates
  dropped, each start within 1 sample period of the previous nominal end.
  Probed days deviated by at most 0.41 samples.
- It holds 566,676..572,401 values (at least 99% of a day).
- Every value lies in -1..1023.
- At most 20% of the values are `-1`.
- The valid values take at least 16 distinct levels.

Days that fail are skipped whole and logged in
`filtered/<id>/ingest_stats.json`. `-1` markers and full-scale 1023 glitches
are kept verbatim; the index records their counts. Structural decode errors
and wrong streams are fatal.

## License

The data are NASA Apollo mission data, released under the NASA SMD
Scientific Information Policy ("information produced from SMD-funded
scientific research activities be made publicly available"):

- The station service lists XA (1969-1977) with `restrictedStatus=open`.
- The archive authors state that it is public at IRIS and PDS.
- There is no CC tag; the DataCite rightsList is empty.

This is the same basis as the accepted NASA PDS recipes. Cite Latham et al.
(1970) and Nunn et al. (2022).

## Scripts

- `download.sh` fetches the inventory, the license pages and one miniSEED day
  per plan row (`nodata=404`). It rejects non-miniSEED or wrong-stream bodies
  on arrival, then fully validates the download. The run fails if fewer than
  70 days, 4 stations or 6 years pass.
- `build.sh` and `verify.sh` use local files only. Verify re-decodes every day
  and compares the bytes, index fields, policy and manifest totals.
