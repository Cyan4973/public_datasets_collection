# NREL ResStock 2021 state end-use load profiles float64 development

## Outcome

Accepted `nrel_resstock2021_state_enduse_load_profiles_f64`: native float64
annual 15-minute energy-consumption profiles of the single-family-detached
housing stock of each contiguous US state plus DC, by end use. Source is
NREL's *End-Use Load Profiles for the U.S. Building Stock*, ResStock 2021
AMY2018 release 1, `timeseries_aggregates/by_state`.

The family is a new source and generation process for the local corpus:
stock-weighted EnergyPlus building-simulation aggregates with full 52-bit
mantissas. It is not a new modality. Energy-load time series already exist
locally as metered material: `electricity_load_diagrams_uci` (f32),
`household_power_uci` and `appliances_energy_uci` (legacy decimal-quantized
f64), and `ceda_ukdale_iam_appliance_power_u16`. Neither the local nor the
downstream corpus has a ResStock, ComStock or OEDI end-use-load-profile
family.

## Source and rights

- Source: OEDI data lake (public anonymous S3 `oedi-data-lake`, not
  requester-pays),
  `nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2021/resstock_amy2018_release_1/timeseries_aggregates/by_state/state=XX/xx-single-family_detached.csv`
- Objects: 49 (48 contiguous states + DC; the release has no AK/HI),
  1,546,682,912 bytes, each pinned by size, single-part ETag md5 and
  LastModified (2021-12-29) in `sources.tsv`. The live listing must match
  the pins on every run.
- Data dictionary pinned by md5 `63dd52cb2464d68104b578f0f898813e`. All 54
  `out.*.energy_consumption` columns are float, kWh; timestamps are EST.
- License: CC BY 4.0. OEDI submission 4520 (DOI 10.25984/1876417): the
  License badge links `https://creativecommons.org/licenses/by/4.0/`, the
  dataset JSON-LD declares the same license, and its distribution
  `contentUrl` covers the
  `nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/`
  prefix. `download.sh` re-checks the license on every run.
- Citation: Wilson et al. (2021), End-Use Load Profiles for the U.S.
  Building Stock, OEDI/NREL, https://doi.org/10.25984/1876417.

## Shape and conversion

The natural record is one `out.<fuel>.<end_use>.energy_consumption` column
of one state file: 35,040 interval-ending 15-minute values,
2018-01-01 00:15 to 2019-01-01 00:00 EST. Each cell is the
shortest-round-trip repr of a double. `float(token)` is written unchanged as
little-endian float64, and verify requires `repr(stored) == token` for every
emitted value.

Selection is global and deterministic:

- The six `*.total` columns are excluded. Each fuel total equals the sum of
  its end uses to ≤3.5e-14 (electricity excluding pv).
- An end use is kept only if, in all 49 states, its series is not all ±0,
  has ≥1,000 distinct values, and is not an exact rescaling of another
  state's series.

Result: 17 of 48 end uses are kept.

- Electricity (13): ceiling_fan, clothes_dryer, clothes_washer,
  cooking_range, cooling, dishwasher, fans_cooling, fans_heating, heating,
  interior_lighting, plug_loads, pumps_heating, water_systems.
- Natural gas (4): clothes_dryer, cooking_range, heating, water_systems.

The 31 dropped end uses are unmodeled or partly-zero columns, or
fixed-schedule columns with 14-168 distinct values per year. The build
checks the result against `columns.tsv`, and verify re-derives the rule
with a different rescaling test.

## Accepted output

- Primary samples: 833 (49 jurisdictions × 17 end uses)
- Primary values: 29,188,320
- Primary bytes: 233,506,560
- Sample size: 35,040 values (280,320 B), all samples
- Value range: 0 to 1.484e7 kWh per interval. Per-end-use maxima run from
  787 (pumps_heating) to 1.48e7 (natural-gas heating). No negatives, no
  -0.0.
- Distinct values per sample: min 1,309 (natural-gas clothes dryer, ME);
  per-end-use medians 29,481-35,040
- Download: 1,547,086,436 B (extraction ratio 15.1%; the bucket serves
  whole CSVs only)

## Caveats

- Simulation output, not measurement.
- Across states, plug_loads and ceiling_fan shapes nearly coincide.
  Nearest-neighbour mean-normalized RMS difference: median 0.28% and 0.57%.
  This affects 98 of 833 samples. Values are full-mantissa, so the low bits
  still differ entirely.
- natural_gas clothes_dryer in ME/DC/VT is 68-76% zeros. DC aggregates only
  153 models.

## Judge checks

- `gate.py`: PASS, no warnings (values 29,188,320; bytes 233,506,560;
  samples 833; median 35,040).
- Ran `verify.sh` myself: OK in 87 s. It covers md5 re-check, an
  independent parser, canonical-repr equality for all values, rule
  re-derivation with identical flags and pair counts, byte-exact compare,
  and index/manifest/stray/duplicate checks.
- Reviewed the driver logs: listing matched 49 pins, check-meta OK,
  `validate: 49 files ok`, build produced 833 samples.
- Confirmed that build/verify/selftest contain no network calls and no
  credentials.
- Byte inspection with `struct`, 60 random samples:
  - 0 float32-exact nonzero values
  - geometric trailing-zero mantissa histogram
  - low-byte entropy 7.997 bits
- Constant stock weight 242.131 in every state. Dividing by it leaves
  uniform residues at decimal steps 1e-1 to 1e-6, so there is no hidden
  quantization lattice.
- Raw-CSV spot checks match the stored doubles exactly (CO gas heating, TX
  cooling last row, DC and ME zeros).
- Annual kWh per represented dwelling is physically plausible: CO gas
  heating 15.8 MWh, FL cooling 6.2 MWh, plug loads 2.0-2.9 MWh.
- Within-state cross-end-use check in 7 states: no proportional pairs
  (closest 2.2% RMS).
- Cross-state similarity for 6 end uses reproduces the builder's disclosed
  near-redundancy figures.
- Rights: opened the stored OEDI 4520 page. Badge href and JSON-LD give CC
  BY 4.0, and the distribution contentUrl covers the exact bucket prefix.
- Novelty: `novelty.py` (OEDI prefix plus ResStock/end-use/load-profile
  terms, and energy-consumption terms) found no prior recipe, registry,
  ledger, downstream or downstream_registry entry beyond this candidate.
  Label: `new_source`.
