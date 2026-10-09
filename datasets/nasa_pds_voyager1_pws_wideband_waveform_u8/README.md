# Voyager 1 PWS wideband waveforms (4-bit codes in uint8)

Raw electric-field waveform codes from the Voyager 1 Plasma Wave Subsystem
(PWS) waveform receiver: 4-bit linear codes 0-15 after a 40 Hz-12 kHz
bandpass and an automatic gain control (AGC), sampled at 28,800 samples/s in
1600-sample lines (55.56 ms) every 60 ms. These are the "sounds" of the
Jupiter and Saturn magnetospheres and of the heliosheath and interstellar
plasma.

- Source: NASA PDS Planetary Plasma Interactions Node, University of Iowa,
  volume `VGPW_1001` (2024-07-26 unified reissue), data set
  `VG1-J/S/SS-PWS-1-EDR-WFRM-60MS-V1.0`,
  <https://space.physics.uiowa.edu/plasma-wave/voyager/data/VGPW_1001/>.
- License: NASA SMD open scientific data policy (public NASA PDS data). The
  volume README only asks users to acknowledge the PDS and the instrument PIs.
- Natural record: one archived 48-second frame `Cmmmmmnn.DAT` (one SCLK
  mod-60 count): a 1024-byte engineering header record, then up to 800
  1024-byte line records (220-byte row prefix + 800 bytes of packed 4-bit
  samples + 4 spare bytes).
- Sample: the codes of every kept line of one frame, samples 17-1600 of each
  line (1584 codes per line), high nibble first, one code per byte, written
  unchanged as `<PRODUCT_ID>.u8`.
- Values: 0-15 only. The label's OFFSET -7.5 maps code c to c - 7.5. The AGC
  gain is not telemetered, so the amplitude scale varies and there is no
  calibration to physical units. uint8 is the narrowest repository width.

## Decode facts (from the volume itself)

- `DOCUMENT/DATATIPS.TXT`: skip record 1; waveform bytes start at byte 221 of
  each record; the SCLK line count is the MSB u16 at bytes 23-24.
- The nibble order (high nibble first, label `START_BIT = 1`) and the offset
  were checked byte-exact against `EXTRAS/SOFTWARE/C/TESTOUT.TXT`, the
  output of the volume's reference `VGPWS_WF_LIST.C` on `TESTIN.DAT`
  (800/800 lines identical).
- `CATALOG/DATASET.CAT`: during the Jupiter encounter the first 16 samples
  (8 bytes) of each line are usually invalid and should be skipped. This
  explains the zeros seen in the scout's probe: 16 zero codes at the start of
  every line in 1979 frames, while 1984+ frames hold real data there. The
  recipe drops these 16 samples on every line of every frame so that every
  line has the same 1584-sample length.
- `CATALOG/DATASET.CAT`: from 1992-11-03 only one line in five is returned,
  and the archive repeats it 5 times in the DAT (line counts still advance).
  Probes of 1998 and 2008 frames show 155 unique lines out of 775 records,
  in exact 5x runs. The recipe keeps only the first copy.
- All-zero waveform records are archive fill for missing lines (the Voyager 2
  test file has 20) and are dropped. `DATA_LINES` in the label counts
  non-fill records, repeats included.

## Selection (discover.py, pinned in sources.tsv)

All 11,415 frames in `INDEX/INDEX.TAB`, sorted by START_TIME, split into
eight mission-phase strata using the DATASET.CAT event table. Picks are
evenly spaced by rank within each stratum. A pick with fewer than 512 records
is replaced by the next unused rank (33 replacements: late-mission frames
are often only 10-11 records long).

| stratum | interval | pool | picks |
|---|---|---|---|
| A_prejupiter | 1978-08-21 .. 1979-02-27 | 562 | 40 |
| B_jupiter | 1979-02-28 .. 1979-03-22 (bow shock to bow shock) | 6,490 | 100 |
| C_jupiter_saturn | 1979-03-23 .. 1980-11-10 | 121 | 30 |
| D_saturn | 1980-11-11 .. 1980-11-16 (bow shock to bow shock) | 41 | 20 |
| E_cruise_full | 1980-11-17 .. 1992-11-02 (all lines) | 579 | 70 |
| F_cruise_decimated | 1992-11-03 .. 2004-12-15 (1 line in 5) | 1,005 | 50 |
| G_heliosheath | 2004-12-16 .. 2012-08-24 | 809 | 40 |
| H_interstellar | 2012-08-25 .. 2023-11-07 | 1,808 | 50 |

Pinned: 400 frames, 322,394,112 DAT bytes + 2,753,860 label bytes +
1,547,057 evidence bytes. Every file is pinned by exact size and by the
upstream MD5 from `EXTRAS/MD5LF.TXT`. Strata A-E frames give about 1.2 M
codes each. F-H frames give about 0.25 M codes each (155 unique lines), so
the quiet post-1992 phases are only about a tenth of the output bytes.

## Scripts

- `discover.py` (author-time, curl only): resolves `sources.tsv`.
- `download.sh`: fetches the evidence files and each pinned LBL/DAT
  (resumable, size + MD5 pinned, stall-based curl limits), cross-checks each
  product against INDEX.TAB, validates every label and walks every record
  before accepting a DAT, and records SHA-256 in `download_plan.tsv`.
- `build.sh` -> `scripts/build.py` (shared decode in `scripts/vgpws.py`):
  emits the samples, `index/<id>/samples.jsonl` and
  `filtered/<id>/ingest_stats.json`.
- `verify.sh` -> `scripts/verify.py`: an independent record walk, line rule
  and nibble unpack. It byte-compares every sample and checks the index, the
  exclusions, value_count = 1584 x kept lines, codes <= 15, all eight strata
  present, all 16 codes used overall, no code above 50% overall, the floors
  and the manifest totals.

## Realized output (build 2026-10-09)

400 samples and 361,186,848 uint8 codes. Median sample 1,252,944 codes; the
smallest is 198,000 (125 lines) and the largest 1,267,200 (800 lines). No
frame was excluded. No all-zero fill lines and no out-of-order line records
were found in the pinned frames. 86,416 repeat records were dropped, all in
the 140 frames from 1992-11-03 onward (F/G/H; 125-161 kept lines each). Every
label `DATA_LINES` equals the non-fill record count.

| stratum | samples | codes | H0 bits min/median/max | largest mode fraction |
|---|---|---|---|---|
| A_prejupiter | 40 | 49,983,120 | 1.30 / 1.44 / 1.86 | 0.531 |
| B_jupiter | 100 | 126,594,864 | 1.33 / 2.79 / 3.62 | 0.526 |
| C_jupiter_saturn | 30 | 37,917,792 | 1.14 / 2.98 / 3.25 | 0.537 |
| D_saturn | 20 | 25,188,768 | 2.97 / 3.11 / 3.50 | 0.210 |
| E_cruise_full | 70 | 87,272,064 | 2.74 / 2.99 / 3.31 | 0.247 |
| F_cruise_decimated | 50 | 12,209,472 | 2.63 / 2.95 / 3.19 | 0.250 |
| G_heliosheath | 40 | 9,806,544 | 2.31 / 2.78 / 3.10 | 0.303 |
| H_interstellar | 50 | 12,214,224 | 2.15 / 2.51 / 3.39 | 0.337 |

All 16 codes occur. Aggregate histogram (codes 0..15): 860,372 / 709,345 /
1,449,372 / 4,565,972 / 10,435,629 / 19,022,273 / 43,759,989 / 90,988,649 /
106,430,381 / 42,323,146 / 21,587,816 / 11,473,742 / 4,804,529 / 1,488,154 /
662,708 / 624,771. Aggregate order-0 entropy is 2.82 bits. The pre-Jupiter
frames (1978-79) are uniformly quiet (in the probed 1979-01-17 frame codes 7
and 8 hold 93%).

`zlsim.py gate`: verdict OK (not redundant), own ratio 6.39, mode share
0.464, no fill warnings. The nearest family is downstream `cov_cover_type`
(distance 0.0789, loss 0.0765). `noaa_isd_lite:isd_day` is
compression-equivalent (loss -0.0081) but statistically distant (distance
0.0897, above the 0.05 threshold). The Cassini RPWS WBR u8 and MIT-BIH ECG
families are not among the 10 nearest.

## Caveats

- Low entropy by nature: quiet frames sit mostly on codes 7/8 (one probed
  1979 approach frame: H0 = 1.47 bits, code 8 = 51%). Encounter frames reach
  about 3.5 bits. The frame rule excludes only frames where one code holds
  more than 80%.
- Gaps between lines (4.44 ms, and 4 lines after 1992-11-03) and missing
  lines are not represented. Kept lines are concatenated in line order.
- Dropping the first 16 samples is applied to every frame, including
  post-Jupiter frames where they are valid (1% of values), to keep one fixed
  rule.
- Interference tones (2.4/4.8 kHz power supply, tape recorder, LECP stepper
  motor, PLS 400 Hz) are part of the archived signal and are not removed.
