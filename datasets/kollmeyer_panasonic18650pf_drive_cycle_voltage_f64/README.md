# Panasonic NCR18650PF Drive-Cycle Cell Terminal Voltage (float64)

This recipe collects the measured terminal voltage of one Panasonic NCR18650PF
Li-ion cell (2.9 Ah, NCA) tested by Dr. Phillip Kollmeyer at the University of
Wisconsin-Madison. The cell sat in a thermal chamber on a Digatron Universal
Battery Tester channel and was driven with drive-cycle power profiles. The
profiles were computed for an electric Ford F150 with a 35 kWh pack and scaled
to one cell: US06, HWFET, UDDS, LA92, a "Neural Network" profile (NN), and
Cycles 1-4, which are random mixes of those. Drive cycles were logged every
0.1 s, and the MAT files store Voltage natively as MATLAB `double`.

One sample is one split single-profile drive-cycle test file, and it holds that
file's complete `meas.Voltage` column as raw little-endian float64.

## Source and pinning

- Download host: the BSEBench Tier-1 raw mirror
  `bsebench-org/panasonic-kollmeyer-2018-raw` on Hugging Face. It re-hosts the
  upstream Mendeley files unchanged and keeps the upstream folder layout. The
  repository is pinned at git revision
  `0f3c96601aa8dcc25f697ef32f3ac918d24433b9`.
- Publisher of record: Mendeley Data, `doi:10.17632/wykht8y7tg.1`. It is not
  reachable from the collection network, so nothing is fetched from it.
- `selection.tsv` pins all 55 files by repository path, size and LFS SHA-256.
  Each URL is an exact `resolve/<revision>/...` URL with the spaces
  percent-encoded.
- `excluded.tsv` lists the other 28 `.mat` files that sit in the covered
  folders, with the reason each one is left out. Preflight fails if the mirror
  tree shows any `.mat` file in those folders that is neither selected nor
  excluded.

## Selection (55 files)

| Folder | Kept split files |
|---|---|
| `25degC/Drive cycles` | Cycle_1..4, US06, HWFTa, HWFTb, UDDS, LA92, NN (10) |
| `10degC/Drive Cycles` | Cycle_1..4, US06, HWFET, UDDS, LA92, NN (9) |
| `0degC/Drive cycles` | Cycle_1..4, US06, HWFET, UDDS, LA92, NN (9) |
| `-10degC/Drive Cycles` | Cycle_1..4, US06, HWFET, UDDS, LA92, NN (9) |
| `-20degC/Drive cycles` | Cycle_1..4, US06, HWFET, UDDS, LA92, NN (9) |
| `-20degC Trise` | Cycle_1..4, US06 (5) |
| `10degC Trise` | Cycle_1..4 (4) |

The 25 degC highway test exists only as two halves, `HWFTa` and `HWFTb`. Each
half is its own upstream file, so each is kept as its own sample.

Excluded:

- The contiguous multi-profile logs: `*_US06_HWFET_UDDS_LA92*`,
  `*_HWFET_UDDS_LA92_NN*`, `0degC_LA92_NN` and `*trise_HWFET_UDDS_LA92_NN*`.
  The upstream readme says these long files mix in charges and pauses logged
  at a lower rate, and that their drive cycles are repeated in the split files.
  In the two Trise folders, the HWFET/UDDS/LA92/NN runs exist only inside such
  a contiguous file. Those four Trise profiles are therefore not collected.
- The `39xx_PreChg/PauseN/ChargeN` segments.
- Never fetched at all: the `Trise with pause(s)` folders, HPPC pulse tests,
  EIS CSVs, `Charges and Pauses`, and the C/20 and 1C capacity tests.
- Only Voltage is emitted. Current, Power, Ah, Wh, battery and chamber
  temperature are different quantities and are not bundled. Time is used only
  to validate the cadence. TimeStamp, a cell array of strings, is skipped.
- The sibling LG 18650HG2 dataset (McMaster/Kollmeyer) is a different cell
  and is not part of this recipe.

## Decode and conversion

`scripts/kollmeyer_mat.py` is a pure-stdlib MAT v5 reader. It does the
following:

1. Checks the 128-byte header (little-endian `IM`, version 0x0100).
2. Inflates every top-level `miCOMPRESSED` element. It rejects truncated
   streams and streams followed by trailing bytes.
3. Walks the `miMATRIX` struct `meas`. This handles packed small data
   elements, 8-byte padding, the field-name-length element and the
   field-name array.
4. Takes `Voltage` as an `mxDOUBLE` N x 1 array stored as `miDOUBLE`, then
   writes those payload bytes unchanged. There is no rounding, resampling,
   reordering or numeric conversion.

Before every download and build, the parser runs a self-test on synthetic MAT
files. It must round-trip a valid file byte-exactly and must reject files that
are out of range, contain NaN, are complex, have a slow cadence, are constant,
are truncated, or carry trailing zlib bytes.

The rules below are shared by download preflight, build and verify. Breaking
any of them is fatal, and no rows are ever dropped or filled.

- Voltage is finite and between 2.0 and 4.4 V. The observed range is
  2.28588-4.32296 V. The four values above 4.25 V are regen pulses near full
  charge in three 10 degC files, `10degC_LA92`, `10degC_Cycle_1` and
  `10degC_Cycle_2`, logged at currents of +5 to +8 A. Regen is included only at
  10 degC and above, and the cell briefly overshoots the 4.2 V charge limit.
- Each file has at least 1,000 rows and at least 500 distinct values.
- Time is finite, non-decreasing and the same length as Voltage.
- The median Time step is between 0.095 and 0.105 s.
- At least 90% of Time steps are about 0.1 s (within 0.02 s).

Samples are named `<seq>_<sample_id>.bin`. They are ordered by test start,
which is also the order of the test campaign.

## Things a user should know

- **Quantization and width.** The tester exported Voltage rounded to 5
  decimals, and the levels sit on a sparse ADC lattice. Consecutive distinct
  levels are mostly 0.14-0.64 mV apart, and a file holds 2,820 to 4,870
  distinct values in 26,557-224,187 rows. The float64 words therefore carry
  far fewer significant digits than float64 allows. They are still the
  source's own stored doubles, with no widening, and they are not
  float32-representable.
- **Cadence.** Drive cycles are logged at 0.1 s, with a logger gap of about
  2 s every ~6,000 rows. Some split files begin with a pre-cycle rest logged
  at a 60 s step. For example, `n10degC_US06` starts with 121 rows at 60 s
  before its 31k rows at 0.1 s. These rows are part of the upstream file and
  are kept. The index records `off_nominal_step_count` and
  `long_steps_over_10s` for each sample.
- **Aging.** The campaign ran from March to July 2017 in the order 25, 10, 0,
  -10, -20 degC, then the Trise runs. The upstream readme says the cell lost
  1C capacity over the campaign, from 2.8 Ah to 2.3 Ah after about 110
  cycles. Later samples therefore come from an aged cell.
- **Test conditions.** Below 10 degC ambient, the profiles carry no regen.
  Drive cycles end at 2.5 V at 25 and 10 degC. At 0, -10 and -20 degC they end
  at 80%, 70% and 60% depth of discharge respectively.

## License

The license is CC BY 4.0, and use requires attribution to
Kollmeyer, Phillip (2018), "Panasonic 18650PF Li-ion Battery Data", Mendeley
Data, V1, doi:10.17632/wykht8y7tg.1. The evidence comes from three places:

- The pinned mirror card states the upstream DOI, the upstream URL and
  "License : CC-BY-4.0".
- BSEBench's Tier-2 sidecars for this dataset repeat CC-BY-4.0.
- The upstream readme asks that the data "be appropriately referenced".

The Mendeley page and the DataCite record could not be fetched from the
collection network. The grant is therefore the mirror's statement of the
upstream license, not a reading of the Mendeley page itself.

## Run

```bash
bash staging/kollmeyer_panasonic18650pf_drive_cycle_voltage_f64/download.sh
bash staging/kollmeyer_panasonic18650pf_drive_cycle_voltage_f64/build.sh
bash staging/kollmeyer_panasonic18650pf_drive_cycle_voltage_f64/verify.sh
```

The download is 113,217,590 bytes of MAT files plus about 70 KB of evidence
and listing files. The realized output is 55 samples holding 4,452,992 float64
values (35,623,936 bytes). Samples range from 26,557 to 224,187 values. The
build and verify steps check the value total against a pinned constant.
