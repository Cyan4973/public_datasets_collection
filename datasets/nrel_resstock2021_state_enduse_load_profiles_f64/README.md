# NREL ResStock 2021 (AMY2018) state single-family-detached 15-minute end-use load profiles (float64)

Full-precision float64 annual 15-minute energy-consumption profiles of the
single-family-detached housing stock of each US state, by end use. They come
from NREL's *End-Use Load Profiles for the U.S. Building Stock*, ResStock 2021
AMY2018 release 1, state aggregates. One sample is one (state, end use)
column: 35,040 values in kWh per 15-minute interval.

| | |
|---|---|
| Source | OEDI data lake, `resstock_amy2018_release_1/timeseries_aggregates/by_state/state=XX/xx-single-family_detached.csv`, 49 files (48 contiguous states + DC; the release has no AK/HI), 1,546,682,912 bytes, each pinned by size, md5 (single-part ETag) and LastModified in `sources.tsv` |
| License | CC BY 4.0. OEDI submission 4520 (DOI 10.25984/1876417): the License badge links `https://creativecommons.org/licenses/by/4.0/`, and the page JSON-LD has `"license": "https://creativecommons.org/licenses/by/4.0/"`. `download.sh` re-checks both on every run |
| Citation | Wilson, E., Parker, A., Fontanini, A., Present, E., Reyna, J., Adhikari, R., et al. (2021). *End-Use Load Profiles for the U.S. Building Stock*. OEDI / NREL. https://doi.org/10.25984/1876417 |
| Primary series | `resstock_sfd_state_enduse_energy_kwh_15min_f64`: 833 samples (49 states × 17 end uses) × 280,320 bytes = 233,506,560 bytes, 29,188,320 values |
| Download | 1,547,086,436 bytes on disk after `download.sh` (49 CSVs plus listing, data dictionary and license page) |

## Material

ResStock models a statistically representative sample of US dwellings
with EnergyPlus through OpenStudio-HPXML, under actual 2018 weather
(AMY2018). It calibrates the result against measured data. The `by_state`
aggregates sum each 15-minute output over all modeled dwellings of one
building type in one state. Each model is weighted by the number of real
dwellings it represents (`units_represented`). The 49 single-family-detached
files aggregate 345,449 models in total, for example:

- CO: 6,036 models for 1,461,502.716 dwellings
- DC: 153 models for 37,046.043 dwellings
- CA: 8,134,633 dwellings, the largest stock

Each file has 59 columns:

- `in.state` and `in.geometry_building_type_recs`: identity, constant
- `timestamp`: interval-ending, Eastern Standard Time with no DST; the data
  dictionary says "timestamp in Eastern Standard Time (EST)"
- `models_used` and `units_represented`: constant per file; kept as index
  metadata only
- 54 `out.<fuel>.<end_use>.energy_consumption` columns, all "float, kWh" in
  `data_dictionary.tsv`: 48 end uses and 6 totals

Every cell is printed as the shortest round-trip repr of a double. Verify
requires `repr(stored) == token` for all 29,188,320 emitted values, and it
passes. Of 561,304 sampled nonzero stored values (every 50th value of every
sample), none round-trips through float32. Float64 is therefore the native
width, not a widening.

## Selection (global, deterministic)

**Totals are excluded a priori.** Over all 49 × 35,040 rows:

- `electricity.total` equals the sum of the electricity end uses excluding
  `pv`.
- The `natural_gas`, `fuel_oil`, `propane` and `wood` totals equal their
  end-use sums. Across all fuel totals the maximum relative deviation is
  3.5e-14.
- `site_energy.total` equals the fuel totals to ≤ 3.9e-7.

The build fails above 1e-9 for fuel totals and above 1e-5 for the site total.
The totals add no information.

**End-use rule.** An end use is kept only if, in **every one of the 49
states**, its series:

- (a) is not all ±0;
- (b) has at least 1,000 distinct values (the repository's per-sample floor);
- (c) is not an exact rescaling of another state's series for the same end
  use. "Exact rescaling" means the same zero pattern and a ratio constant to
  1e-9 relative.

Every state therefore contributes the same end uses, and the claimed scope
is exact. `columns.tsv` pins the keep/drop outcome for all 54 columns. The
keep list was pinned from range probes before download, and the full-file
build reproduced it exactly. Its `evidence` column now records the realized
per-column numbers from `filtered/<id>/column_selection.json`. `build.sh`
fails if a rebuild disagrees. `verify.sh` re-derives the rule with a
different rescaling test (sum-normalized profiles instead of ratio spreads)
and requires identical flags, pair counts and zero-state lists.

Realized outcome:

| Outcome | End uses |
|---|---|
| **kept (17)** | electricity: ceiling_fan, clothes_dryer, clothes_washer, cooking_range, cooling, dishwasher, fans_cooling, fans_heating, heating, interior_lighting, plug_loads, pumps_heating, water_systems; natural_gas: clothes_dryer, cooking_range, heating, water_systems |
| (a) all ±0 in all 49 states (6) | ext_holiday_light, house_fan, pumps_cooling, recirc_pump, vehicle, wood heating (not modeled in this release) |
| (a) all ±0 in 1-9 states (11) | electric heating_supplement (VT), electric pool_heater (CO ID MT OR UT WA WY), pv (AL GA KY MS ND NE SD WV WY), fuel_oil heating (AR AZ NM UT) and water_systems (DC ND SD), natural_gas hot_tub_heater (CT DC MA ME NH RI VT), lighting (DC) and pool_heater (DC ME VT), propane clothes_dryer, heating and water_systems (DC) |
| (b) only (4) | bath_fan (min 20 distinct values per year), range_fan (14), extra_refrigerator (91), propane cooking_range (15 in DC) |
| (b) and (c) (10) | refrigerator, freezer, exterior_lighting, garage_lighting, hot_tub_heater, hot_tub_pump, pool_pump, well_pump, natural_gas fireplace and grill: 72-168 distinct values per year, and 168-184 state pairs are exact rescalings |

The fixed-schedule end uses follow one hourly appliance schedule with
monthly multipliers, scaled by each state's stock. States in the same time
zone are therefore bit-level rescalings of each other: 168-184 of 1,176 pairs
per end use, e.g. refrigerator NY/NJ = 1.7617652416452299 ±4e-16. Rule (b)
alone already drops all of them, so (c) never decides on its own in this
data. It documents why those columns would have been 49 near-duplicates.

The kept end uses are rich:

- At least 1,309 distinct values per sample (natural_gas clothes_dryer, ME).
- Per end use, the median sample has 29,481-35,040 distinct values out of
  35,040.

## Homogeneity

All 833 samples are one quantity: energy in kWh per 15-minute interval. They
come from one generation process (one ResStock release, one EnergyPlus
workflow, one weather year, one sampling-weight scheme), one building type,
one aggregation level (state), one cadence and one 35,040-step time lattice.
Natural-gas end uses are reported in kWh by the source itself, not converted
here.

End uses and states differ in scale. Realized per-end-use maxima run from
787 kWh (`pumps_heating`) to 1.48e7 kWh (`natural_gas.heating`). That reflects
state stocks spanning 37k (DC) to 8.1M (CA) dwellings and end uses that
differ in power. No kept value is negative. These are unquantized
full-mantissa doubles, not a tick lattice, so scale moves only the exponent
and the 52-bit mantissa content is of the same kind across samples. Within a
sample the scale is coherent.

The accepted ClimSim recipe
(`leap_climsim_lowres_e3sm_mmf_state_fields_f64`) is the precedent for
admitting physics-model output as source material. ClimSim deliberately kept
one variable per family. Here the analogous unit is "simulated
energy-consumption profile": all end uses share the unit and the
model/weighting path. The intensity (kWh/sqft) columns, other building
types, county/PUMA aggregates, ComStock and later ResStock releases are
never mixed in. If a judge prefers a narrower family, an electricity-only
variant (13 end uses × 49 = 637 samples, 178,563,840 bytes) is a small
change. It needs an explicit fuel exclusion applied after the rule in
build/verify, plus `columns.tsv` and manifest updates. The rule itself keeps
the four natural-gas end uses, so it cannot be done by editing the pins
alone.

## Novelty

Energy-load time series are a **known modality** locally:

- `electricity_load_diagrams_uci`: f32, measured 15-minute kW per client
- `household_power_uci`: f64, one household, kW printed to 3 decimals
- `appliances_energy_uci`: f64, one house, Wh in steps of 10

At 64-bit, the existing families are decimal-quantized single-site meter
prints widened to double. This recipe is a **new source and generation
process**: stock-weighted building-simulation aggregates with full 52-bit
mantissas and many states and end uses. It is not a new modality.
`tools/autocollect/novelty.py` found no ResStock/ComStock/OEDI
end-use-load-profile match in recipes, registry, ledger or downstream.

## Download, build, verify

`download.sh` (anonymous curl only; 240 s in the driver run):

1. Synthetic self-test (`scripts/selftest.py`).
2. Live ListObjectsV2 of the `by_state/` prefix. It must hold exactly the 49
   pinned keys, with pinned Size, ETag and LastModified.
3. `data_dictionary.tsv` (md5 pinned; 54 columns float/kWh; EST) and the OEDI
   page (title, DOI, JSON-LD CC BY 4.0).
4. One-byte range liveness GET.
5. 49 CSVs via `curl -C -` into `.part` files. The script uses
   `--speed-limit 1024 --speed-time 120` (no `--max-time`), curl retries and
   an outer retry loop. Each file must match its pinned size and md5 before
   it is renamed. Finished files are re-checked on reruns.
6. `resstock.py validate` parses all 49 files completely, and any violation
   of the missing-value policy is fatal. The checks are:
   - the pinned 59-column header
   - exactly 35,040 rows on the 2018-01-01 00:15 .. 2019-01-01 00:00 lattice
   - state and building type on every row
   - finite cells
   - constant models_used/units_represented
   - fuel totals equal to their end-use sums

`build.sh` (about 75 s) re-parses the files and applies the rule, writing the
per-column evidence to `filtered/<id>/column_selection.json`. It then checks
the keep list against `columns.tsv` and writes:

- `samples/<id>/resstock_sfd_state_enduse_energy_kwh_15min_f64/<STATE>__<fuel>.<end_use>.f64le.bin`:
  float64 LE, timestamp order, signed zeros preserved
- `index/<id>/samples.jsonl`, with the required fields plus state, source
  column, fuel, end use, unit, lattice endpoints, models_used,
  units_represented, source key and md5, and min/max/distinct/zero/negative
  counts from the stored doubles, plus sha256
- `filtered/<id>/ingest_stats.json`

`verify.sh` (`scripts/resstock_verify.py`, about 90 s) shares no parsing
code with the build:

- re-checks every file's md5
- parses with a plain line/field splitter and an epoch-based timestamp
  lattice
- requires `repr(value) == token` for every emitted value
- re-derives the rule with sum-normalized profile comparison
- compares every sample byte-for-byte (`struct.pack('<35040d')`)
- checks every index field and the manifest `sample_count`/`total_size_bytes`
- rejects stray files, duplicate samples and samples with fewer than 1,000
  distinct values

`scripts/selftest.py` builds synthetic files with the real header and checks:

- both parsers agree bit-exactly, including -0.0
- both rule implementations give the designed a/b/c outcomes, including
  negative-ratio rescaling and a 1e-6 near-miss
- 13 corruptions are rejected: NaN/empty/inf cells, wrong timestamp, state or
  building type, missing rows, extra column, changing models_used,
  inconsistent fuel total, non-canonical token, header change

## Caveats

- **Simulation, not measurement.** The values are model outputs weighted to
  a stock, not metered loads.
- **Some kept end uses look alike across states.** Large-state aggregates of
  stochastic occupant schedules converge toward a common shape. After
  dividing each full-year series by its mean, the relative RMS difference
  between two states is:

  | End use | Median over the 1,176 state pairs | Minimum |
  |---|---|---|
  | plug_loads | 5.2% | 0.17% (NY/PA) |
  | ceiling_fan | 15% | 0.34% (NY/PA) |
  | interior_lighting | 30% | 1.3% (NY/NJ) |
  | water_systems (electric and gas) | about 18% | not computed |
  | HVAC heating, cooling and fans | 55-62% | not computed |

  None of these are exact rescalings, so rule (c) keeps them. The 49
  plug_loads samples are still the weakest part of the family: a shared
  shape plus about 5% state-specific variation. Dropping plug_loads would
  need an explicit exclusion after the rule, and would leave 784 samples.
- **Columns are related within a state.** Examples: cooling vs fans_cooling;
  electric vs gas versions of the same appliance. In range probes no
  within-state pair of kept columns was proportional (minimum sampled ratio
  spread 35%).
- **Sparse samples.** natural_gas clothes_dryer in ME (1,309 distinct values,
  76% zeros), DC (1,322, 74%) and VT (1,917, 68%) passes rule (b) but is
  mostly zeros. Up to 33-44% of intervals are zero for space heating and
  heating pumps in warm states. DC aggregates only 153 models, so its
  columns are noisier.
- **Extraction ratio.** 15.1% of downloaded bytes are kept (1.547 GB →
  0.234 GB). The bucket serves whole CSVs only; no anonymous column
  projection exists.
