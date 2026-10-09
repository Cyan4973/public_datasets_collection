# GRAIL LGRS KBR1C Ka-band inter-satellite ranging, extended mission (float64)

This recipe collects the inter-spacecraft Ka-band ranging observables of
NASA's GRAIL lunar gravity mission. The Lunar Gravity Ranging System (LGRS)
on GRAIL-A and GRAIL-B measured their separation by dual one-way
carrier-phase ranging. The Level-1B KBR1C products (PDS dataset
GRAIL-L-LGRS-3-CDR-V1.0, volume GRAIL_0101, archived by the PDS Geosciences
Node) publish one ASCII file per UTC day. Columns 2-4 of each record are:

| series | DPSIS Table 43 column | unit | role |
|---|---|---|---|
| `kbr1c_biased_range_f64` | 2, biased dual one-way range | m | primary |
| `kbr1c_range_rate_f64` | 3, range rate | m/s | primary |
| `kbr1c_range_accl_f64` | 4, range acceleration | m/s² | primary |
| `kbr1c_tdb_seconds_i64` | 1, TDB s past 2000-01-01 12:00 | s | auxiliary |

Each daily product becomes one sample per series. All four series come from
the same records in source order, so they stay aligned.

    bash staging/grail_lgrs_kbr1c_ka_band_ranging_f64/download.sh   # ~1.43 GB, host ~1.7 MB/s
    bash staging/grail_lgrs_kbr1c_ka_band_ranging_f64/build.sh
    bash staging/grail_lgrs_kbr1c_ka_band_ranging_f64/verify.sh

`discover.sh OUT.tsv` documents how `sources.tsv` was resolved. It fetches
only the volume MD5 manifest and the first 4 KB of each product.

## Scope

The scope is every KBR1C product of the GRAIL **extended mission**,
2012-08-30 to 2012-12-14: 107 daily files at a **2 s cadence**, 4,578,310
records and 1,431,187,536 bytes served.

The 90 primary-mission products (2012-03-01 to 2012-05-29) are excluded.
They have a 5 s cadence (17,280 records/day) and a different orbit, which
gives a different sampling lattice and dynamic range. Mixing them would put
two regimes into one series. They could form a separate recipe.

Realized boundaries as published (nothing spliced or filled):

- `2012_08_30` starts at 16:31:38 (13,373 records). `2012_12_14` ends at
  20:54:42 (37,195 records), at the end of the mission. The errata date the
  end of the extended-mission science phase to 2012-12-12. 12-13 and 12-14
  are kept because they use the same instrument, product version and cadence.
- 28 other days have 42,501 to 43,122 of 43,200 epochs. Most are the weekly
  Ka boresight-calibration days. Upstream interpolates gaps of up to 20 s, so
  longer gaps are absent records.
- After a gap a new carrier-phase arc starts with a new unknown bias, so the
  **biased range jumps** there. One probed example is +34.5 km after a 956 s
  gap on 2012-12-10. This is source semantics, not a defect. Range rate and
  acceleration carry no bias. The index records `gap_count`,
  `missing_epochs`, `max_gap_s`, `gaps` and `rebias_steps` per sample. The
  auxiliary TDB series gives exact epochs.
- Records flagged with quality digit 1 ("from raw data for Ka boresight
  calibration slew") are kept and counted (`calslew_flag_records`).

## Format and conversion

The files are CRLF ASCII. Each has a header of 23 or 27 `KEY : value` lines
followed by `END OF HEADER`; `NUMBER OF HEADER RECORDS` counts the lines
before `END OF HEADER`. After the header, each record is 20
whitespace-separated columns (DPSIS Table 43, confirmed against the
DPSIS.HTM in `document/`). The doubles are printed with 16 to 17 significant
digits, for example `-29030.1360341154 0.07050382816793005
0.0008263486055854205`. `float()` gives the correctly rounded IEEE-754 double,
which is stored as `<d`. The values are not float32-representable, so float64
is the native width.

## Validation

- `download.sh`:
  - checks the pinned SHA-256 of `grail_0101_230316.md5` and that every
    pinned MD5 is listed in it;
  - checks each label's MD5, PRODUCT_ID and DATA_SET_ID;
  - checks each product's served size and published MD5;
  - runs a full parse of each product. The parse requires the header fields
    (ASCII format, GRAIL A+B, J2000-noon epoch, level 1C), 20 columns per
    record, finite values within generous physical bounds, valid 8-digit
    flags, a record count and first/last TDB matching the header and
    `sources.tsv`, and TDB steps that are positive multiples of 2 s.
- The header `FILESIZE (BYTES)` describes the LF original and is smaller than
  the served CRLF file. It is pinned, but the served size and MD5 are what is
  checked.
- `verify.sh` does not import the build parser. It:
  - re-checks the size and MD5 of every product;
  - re-parses each product with its own byte-level reader and re-derives all
    four samples byte for byte;
  - checks that the published range rate integrates to the range within each
    arc (≥ 99% of steps within 1 m);
  - checks the index fields, SHA-256 and stored min/max, and the manifest
    totals;
  - rejects constant, low-distinct or float32-representable samples.

Realized output (build and verify run 2026-10-08): 321 primary samples, 13,734,930 values and 109,879,440 bytes
(36,626,480 per series), plus 36,626,480 auxiliary bytes. Samples hold
13,373 to 43,200 values each (median 43,200), and every primary sample has all-distinct values. Realized ranges: biased range -211,773 to +475,435 m (the per-arc bias sets the level), range rate -1.23 to +1.18 m/s, range acceleration -4.2e-3 to +3.4e-3 m/s². 30 days have 38 gaps (8,783 missing epochs, longest 996 s); there are 29 re-bias steps on 25 days and 31,202 calibration-slew-flagged records.

## License

The data are NASA PDS archive data under the NASA SMD open scientific data
policy (https://science.nasa.gov/researchers/science-data/science-information-policy/).
No restriction is stated in the labels, AAREADME or dataset catalog. Cite:
Kahan, D.S., GRAIL LGRS Calibrated and Resampled Science Data Set V1.0,
GRAIL-L-LGRS-3-CDR-V1.0, NASA Planetary Data System, 2012.
