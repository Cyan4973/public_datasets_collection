# Kollmeyer Panasonic NCR18650PF drive-cycle terminal-voltage float64 development

## Outcome

Accepted `kollmeyer_panasonic18650pf_drive_cycle_voltage_f64`.

Each sample is the measured terminal voltage of one Panasonic NCR18650PF Li-ion cell (2.9 Ah, NCA) under one drive-cycle power profile. The profiles were computed for an electric Ford F150 and scaled to one cell. The tests ran at the University of Wisconsin-Madison on a Digatron Universal Battery Tester inside a thermal chamber, and drive cycles were logged every 0.1 s. This is a new quantity for the corpus. The only other battery family, `zenodo_battery_eis_complex_f32`, holds impedance spectra. Downstream `power_voltage` is household mains voltage.

## Source and rights

- Download host: the BSEBench Tier-1 raw mirror `bsebench-org/panasonic-kollmeyer-2018-raw` on Hugging Face, pinned at git revision `0f3c96601aa8dcc25f697ef32f3ac918d24433b9`. It keeps the upstream `Panasonic 18650PF Data/` layout and serves the files unmodified.
- Publisher of record: Mendeley Data, Kollmeyer (2018), V1, `doi:10.17632/wykht8y7tg.1`. Nothing is fetched from Mendeley.
- Selection: 55 `.mat` files, 113,217,590 bytes in total. `selection.tsv` pins each file by path, size and LFS SHA-256.
- Exclusions: `excluded.tsv` lists the other 28 `.mat` files in the covered folders, namely 6 contiguous multi-profile logs and 22 `39xx` charge/pause segments. Preflight fails if any file in those folders is in neither list.
- License: CC BY 4.0. Attribution: Kollmeyer, Phillip (2018), "Panasonic 18650PF Li-ion Battery Data", Mendeley Data, V1, doi:10.17632/wykht8y7tg.1.
- Rights evidence:
  - The pinned mirror card (sha256 `f33e6b30…4050c0`) gives the upstream DOI and URL and says "License : CC-BY-4.0".
  - The BSEBench Tier-2 sidecar `panasonic_18650pf__us06_v1__T25.card.json` says `"license": "CC-BY-4.0"` and `"provenance": "Kollmeyer (Mendeley)"`.
  - The upstream readme says "If this data is utilized for any purpose, it should be appropriately referenced."
- Caveat: the collection network's proxy returned 403 for the Mendeley landing page and the DataCite record, so the grant could not be read at its source. It is taken from the mirror's statement of the upstream license, and the manifest and README say so.

## Shape and conversion

- Natural record: one split single-profile drive-cycle test file, i.e. one profile at one ambient condition. The 25 °C highway test exists upstream only as two halves, `HWFTa` and `HWFTb`, and each half is kept as its own sample.
- Samples per condition:

| Condition | Samples |
|---|---|
| 25 °C | 10 |
| 10 °C | 9 |
| 0 °C | 9 |
| −10 °C | 9 |
| −20 °C | 9 |
| −20 °C Trise | 5 |
| 10 °C Trise | 4 |

- Decode: a pure-stdlib MAT v5 reader checks the 128-byte header and inflates each `miCOMPRESSED` element with strict zlib EOF and trailing-byte checks. It then walks struct `meas` and takes `Voltage` as an mxDOUBLE/miDOUBLE N×1 array. Those payload bytes are written unchanged, with no numeric conversion and no widening.
- Not emitted: `Current`, `Power`, `Ah`, `Wh` and the temperature columns. `Time` is used only to validate the cadence.
- Rules: build, preflight and verify all enforce these, and breaking any one is fatal. No rows are dropped or filled.
  - Voltage is finite and within 2.0–4.4 V.
  - Each file has at least 1,000 rows and at least 500 distinct values.
  - Time is non-decreasing, its median step is 0.095–0.105 s, and at least 90% of steps are within 0.02 s of 0.1 s.
- Excluded material:
  - Mixed-rate contiguous logs. Upstream says the split files repeat their drive cycles. One consequence: the HWFET, UDDS, LA92 and NN runs of the two Trise campaigns are not collected, because they exist only inside these logs.
  - Trise-with-pause folders, HPPC, EIS, charge/pause segments and the capacity tests.
  - The LG HG2 sibling cell.

## Accepted output

- Primary samples: 55
- Primary values: 4,452,992 (little-endian float64)
- Primary bytes: 35,623,936
- Minimum sample: 26,557 values (`n20degC_US06`)
- Median sample: 75,811 values
- Maximum sample: 224,187 values (`25degC_UDDS`)
- Global voltage range: 2.28588–4.32296 V
- Distinct levels per file: 2,820–4,870, all exact 5-decimal values
- Off-nominal time steps: 2,501 in total. These are 60 s pre-cycle rests at the start of 14 files and occasional ~2 s logger gaps, all kept as recorded and counted per sample in the index.
- Aggregate SHA-256 of the concatenated samples in sequence order: `f4835fbe636f40eae25885b94aac661b64e636f7782fbf409585fd134b09e777`

Known properties:

- **Thin precision.** The values sit on a sparse ADC lattice, so each float64 word carries few significant digits. They are still the source's own stored doubles: only 0.14% are float32-representable.
- **Cell aging.** 1C capacity fell from 2.8 to 2.3 Ah over the March–July 2017 campaign. Samples are ordered chronologically.

## Judge checks

- **Gate:** I re-ran `tools/autocollect/gate.py`. It passed with no warnings: 55 samples, 4,452,992 values, median 75,811, width 64.
- **Verify:** I re-ran `verify.sh`, which re-decodes all 55 sources and compares bytes, index rows, summary and manifest totals. It reported "verify ok".
- **Download:** the driver's log shows all 55 files matched their pinned size and SHA, and preflight passed. `build.sh` reads only local files, and there are no credentials in any script.
- **Bytes, read with struct across all 55 samples:**
  - Per-file ranges and means fit an 18650 discharged to the 2.5 V or DOD cutoff.
  - The 4.32 V maximum coincides with +6.6 A of regen current in the decoded `Current` column.
  - The gaps between adjacent levels (about 0.15 mV and 0.48–0.65 mV) follow the same pattern in every file, so this is one lattice.
  - Only 6,313 of 4,452,992 values are float32-representable, so nothing was widened.
- **Overlap:** no 256-value window appears in two samples. All 844 matching 64-value windows hold 1–6 distinct values, i.e. rest plateaus. The rest prefixes of split files that share a start time differ value by value.
- **Cadence:** decoding `Time` confirms the 0.1 s logging, the 59- or 119-step 60 s rest prefixes in 14 files, and the ~2 s logger gaps.
- **Rights:**
  - I read the pinned mirror card and fetched the Tier-2 sidecar, which states CC-BY-4.0.
  - BSEBench assigns licenses per source across its org (CC0, "other", MIT, CC BY), so this label is deliberate rather than boilerplate.
  - The Mendeley, DataCite, doi.org, OpenAlex, Semantic Scholar and GitHub hosts all returned proxy 403 to me.
- **Novelty:** I ran `novelty.py` on both resource URLs with distinctive terms. The only hits for the source were this candidate itself. I opened the bytes of downstream `power_voltage` and confirmed it is mains voltage (about 234 V, two decimals), a different quantity.
- **Minor documentation imprecision, not material:**
  - The README says a 2 s logger gap comes about every 6,000 rows; I see roughly one per 10–14k rows.
  - The README says `n10degC_US06` has "121 rows at 60 s"; the data has 119 steps of 60 s.
  - The index records the exact counts in both cases.
