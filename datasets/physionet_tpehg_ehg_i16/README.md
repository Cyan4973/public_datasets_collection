# PhysioNet Term-Preterm EHG Database: unfiltered electrohysterogram int16

This recipe collects the native signed-16-bit ADC codes of the three
unfiltered bipolar abdominal electrohysterogram (EHG, uterine EMG) channels
from all 300 recordings of the PhysioNet Term-Preterm EHG Database v1.0.1
(TPEHG DB, DOI 10.13026/C2FW2V). One sample is one complete channel of one
recording: about 30 minutes at 20 Hz (15,060 to 39,873 values, median 35,350).

- Source: <https://physionet.org/content/tpehgdb/1.0.1/>, fetched from
  PhysioNet's anonymous open-data mirror
  `https://physionet-open.s3.amazonaws.com/tpehgdb/1.0.1/`
- License: Open Data Commons Attribution License v1.0 (ODC-By-1.0), stated on
  the project page with an open "anyone can access" policy. Cite Fele-Zorz et
  al., Med Biol Eng Comput 46(9):911-922 (2008), the dataset DOI, and
  PhysioNet.
- Output: 900 samples (300 records x 3 channels), 31,967,703 int16 values,
  63,935,406 bytes, in two primary series of the same quantity:

| series | records | samples | values | bytes | ADC code lattice |
| --- | ---: | ---: | ---: | ---: | --- |
| `tpehg_ehg_unfiltered_adc_step1_i16` | 174 | 522 | 18,356,100 | 36,712,200 | full 16-bit codes (step 1) |
| `tpehg_ehg_unfiltered_adc_step16_i16` | 126 | 378 | 13,611,603 | 27,223,206 | two adjacent residues mod 16 (step 16) |

## Run

```bash
bash staging/physionet_tpehg_ehg_i16/download.sh   # ~256.1 MB
bash staging/physionet_tpehg_ehg_i16/build.sh
bash staging/physionet_tpehg_ehg_i16/verify.sh
```

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/physionet_tpehg_ehg_i16/`.

## Source layout

Each record is a WFDB pair `tpehgdb/tpehgNNNN.hea` + `.dat`. The `.dat` holds
12 frame-interleaved format-16 signals, in the order `1`,
`1_DOCFILT-4-0.08-4`, `1_DOCFILT-4-0.3-3`, `1_DOCFILT-4-0.3-4`, `2`, ...,
`3_DOCFILT-4-0.3-4`. Signals `1`, `2`, `3` (indices 0, 4, 8) are the
unfiltered bipolar channels S1 = E2-E1, S2 = E2-E3, S3 = E4-E3 (four
electrodes 3.5 cm from the navel), digitized with 16-bit resolution over
+/-2.5 mV (13107 ADC units per mV). The `DOCFILT` signals are offline 4-pole
Butterworth band-pass versions of the same channels (0.08-4, 0.3-3,
0.3-4 Hz). They are derived, so this recipe drops them.

All 300 headers share the same layout: 12 signals, format 16, gain 13107/mV,
ADC resolution 16, ADC zero 0. The sampling frequency is written either as
`20.000000` (174 records) or `20.000110` (126 records). Both are accepted,
and each index row records the header value unchanged.

## Two ADC code lattices

The built output showed that the two frequency strings line up exactly with
two quantization regimes. I measured all 900 channels on 2026-10-05:

- `20.000000` records: the codes use the whole step-1 lattice. All 16
  residues mod 16 occur, and the two most common ones hold only 0.127 to
  0.157 of the values. Every channel has at least 703 distinct values.
- `20.000110` records: every value falls on exactly two adjacent residues
  mod 16 (for example `16k+11` and `16k+12`). The effective resolution is
  therefore about 12 bits, scaled by 16 into the 16-bit code range. These
  records probably come from a different acquisition setup, which would also
  explain the different nominal clock. They span the same unit, scale and
  amplitude range.

Criteria require one tick lattice per regime, so the two regimes become
separate primary series instead of one mixed series. The stored codes are
never rescaled. The header frequency string decides which series a record
goes to. Build and verify both assert the lattice on every channel: step 1
needs all 16 residues and a top-2 share of at most 0.5; step 16 needs at most
two adjacent residues. Either series alone clears the acceptance floors, and
the step16 series can be dropped without affecting the step1 series.

## What the scripts do

- `download.sh` fetches `SHA256SUMS.txt`, which is pinned by hash. It then
  fetches `RECORDS`, checked against that list, and the 300 `.hea`/`.dat`
  pairs, using resumable curl with stall detection. It also fetches the
  project page and fails if the page no longer names the ODC-By 1.0 license.
  `scripts/validate_download.py` then checks every file's SHA-256, the header
  layout, `.dat size == frames * 24`, and the aggregate byte and frame counts.
  Any file with a bad checksum is deleted, so a re-run fetches it again.
- `build.sh` (`scripts/tpehg_build.py`) uses only local files. For each
  record it checks the initial value and 16-bit WFDB checksum of all 12
  signals and asserts the channel lattice. It then writes signals 0, 4 and 8
  unchanged as little-endian int16 to
  `samples/physionet_tpehg_ehg_i16/<series>/<record>_ch<1|2|3>.bin`.
  It also writes `index/physionet_tpehg_ehg_i16/samples.jsonl` and
  `filtered/physionet_tpehg_ehg_i16/ingest_stats.json`.
- `verify.sh` (`scripts/tpehg_verify.py`) shares no code with the build. It
  re-hashes the sources from `SHA256SUMS.txt`, re-parses the headers,
  re-decodes the frames with explicit little-endian `struct` unpacking, and
  re-checks all 12 checksums and the lattice. It then compares every sample
  byte and every index field, rejects extra files, extra index keys,
  duplicates and degenerate channels, and checks each series' manifest
  `sample_count` and `total_size_bytes`.

## Missing values and degeneracy

Nothing is dropped, clipped, or imputed. WFDB's `-32768` invalid-sample code
and the `+32767` rail are kept as they are and counted per sample
(`saturated_low_count`, `saturated_high_count`); neither occurs in this
release. A channel fails both build and verify if it is constant, has fewer
than 32 distinct values, changes value on fewer than 5% of steps, or has more
than 50% rail values.

Some step1 channels contain large real excursions close to the rails, for
example tpehg725, tpehg800 and tpehg1167, whose range reaches about
-32745..32734. One channel, tpehg1241 channel 3, opens with a constant run of
1,133 values (about 57 s at code 25313). All of these are preserved as
recorded.

## Privacy

These are de-identified recordings from 300 pregnancies. The header comments
contain clinical fields: gestation, age, parity, abortions, weight,
hypertension, diabetes, placental position, bleeding, funneling and smoking.
None of them is emitted. The `tpehgdb.smr` summary and the `.fvl` feature
tables are not downloaded. Index rows hold only the record id, channel,
signal geometry, the header sampling-frequency string, the lattice label, and
value statistics.
