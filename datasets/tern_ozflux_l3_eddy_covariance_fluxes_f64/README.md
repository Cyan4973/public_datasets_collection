# TERN OzFlux L3 half-hourly eddy-covariance fluxes (float64)

This recipe collects quality-controlled 30-minute turbulent surface fluxes from
the TERN Ecosystem Processes / OzFlux tower network. The fluxes are computed by
eddy covariance from a sonic anemometer (CSAT3/CSAT3A/CSAT3B or IRGASON) and an
open-path IRGA (LI-7500 family or IRGASON) at each tower. All files are
processed to Level 3 by one chain, PyFluxPro ("default" folder): QA/QC applied,
not gap-filled. There are three primary series, one per flux variable, because
the units differ:

| series | source variable | units |
|---|---|---|
| `ozflux_l3_fco2_f64` | `Fco2`, CO2 flux | umol m-2 s-1 |
| `ozflux_l3_fe_f64` | `Fe`, latent heat flux | W m-2 |
| `ozflux_l3_fh_f64` | `Fh`, sensible heat flux | W m-2 |

Each tower file gives one sample per variable: every valid half-hour value, in
time order, as raw little-endian IEEE float64. The values are the native
NetCDF Float64 data; only the byte order changes.

## Scope

`files.tsv` pins 51 files from 46 sites. For each site the recipe takes the
newest release folder (2024_v2 .. 2026_v3, as crawled on 2026-10-09) and every
file in its `L3/default/` folder. These files have 6,432,235 half-hour steps per
variable. Two files are excluded because they use 60-minute steps:
`Otway/2024_v2/.../Otway_L3.nc` and
`Tumbarumba/2026_v2/.../Tumbarumba1_..._L3.nc`. Keeping them out holds the
family to a single tick lattice. `scripts/discover.py` documents how the list
was resolved and can re-derive it. The pipeline does not call it.

Five sites have two files: AliceSpringsMulga, Samford, TiTreeEast, Whroo and
WombatForest. In each case the second file covers a separate tower or period
(for example `Whroo1` from 2011 to 2024 and `Whroo2` from 2025 to 2026), so
each file is its own natural record.

## Acquisition

`download.sh` uses curl only. For each row of `files.tsv` it fetches the
OPeNDAP `.dds` and `.das` and checks them:

- the time length matches `files.tsv`
- Fco2, Fe and Fh are `Float64[time][1][1]`
- the units are as expected
- any declared `_FillValue` is -9999.0
- `time_step` is 30 and `processing_level` is L3
- `license_name` is "CC BY 4.0"

It then fetches three server-side projections,
`<file>.nc.dods?Fco2.Fco2`, `?Fe.Fe` and `?Fh.Fh`. Each `.dods` payload is
validated in turn:

- DDS declaration and dataset path
- the `\nData:\n` separator
- two equal big-endian uint32 XDR length words equal to the pinned time length
- the exact byte length

Invalid payloads are re-fetched up to three times before the script aborts.
The expected download is about 156 MB.

## Missing values

L3 marks missing or rejected half-hours with -9999.0. Thirty-one files declare
it as `_FillValue`; the other 20 use it without declaring it. In the realized
build the fill share is 29.9% for Fco2, 26.6% for Fe and 25.1% for Fh. Per file
it reaches about 50% (WombatStateForest, SamfordEcologicalResearchFacility and
YarramundiIrrigated Fco2), so dropping fill rather than keeping it as a mode
value is deliberate.

The build drops -9999.0, NaN/Inf and the NetCDF default fill value, and keeps
the rest in time order. The positions of the fill runs are written to
`filtered/<id>/gaps/<series>/<stem>.json`, so alignment to the half-hour axis
can be rebuilt.

The upstream `valid_range` attribute is not enforced at L3. Probes found Fe up
to 1131 W m-2 against a declared range of -100 to 600, so the recipe does not
apply it. A finite non-fill value beyond 1e5 is fatal. A (file, variable) pair
with fewer than 1000 valid values is skipped and listed in
`filtered/<id>/ingest_stats.json`.

## Verification

`verify.sh` re-decodes every payload with a separate implementation
(`array('d')` plus `byteswap`) and applies the same policy. It then checks:

- every sample byte for byte
- the index counters, min/max and SHA-256
- the gap sidecars
- the manifest sample counts and byte totals
- the median floor

It also rejects constant samples, samples with few distinct values, and
samples made only of integers.

## License

CC BY 4.0. Every file's global attributes declare it (`license`,
`license_name`). Attribution: TERN Ecosystem Processes / OzFlux, plus the
acknowledgement string recorded in `manifest.toml`.

```bash
bash staging/tern_ozflux_l3_eddy_covariance_fluxes_f64/download.sh
bash staging/tern_ozflux_l3_eddy_covariance_fluxes_f64/build.sh
bash staging/tern_ozflux_l3_eddy_covariance_fluxes_f64/verify.sh
```

## Realized output (build of 2026-10-09)

| series | samples | values | bytes | smallest / median sample (values) |
|---|---|---|---|---|
| `ozflux_l3_fco2_f64` | 51 | 4,506,743 | 36,053,944 | 5,868 / 62,630 |
| `ozflux_l3_fe_f64` | 51 | 4,718,845 | 37,750,760 | 5,875 / 64,998 |
| `ozflux_l3_fh_f64` | 51 | 4,816,998 | 38,535,984 | 5,873 / 71,885 |

The total is 153 samples and 112,340,688 bytes, from a 156,226,795-byte
download. No pair was skipped. Value ranges: Fco2 -66.4 to 54.2, Fe -568 to
1757 (Tumbarumba), Fh -612 to 938.

## Breadth (zlsim gate, 2026-10-09)

Verdict OK, no series redundant (thresholds: loss <= 0.03 and distance <= 0.05).
All three series behave like full-mantissa noisy doubles (own ratio about 1.16),
so they sit close to the thresholds:

| series | own ratio | nearest family (distance / loss) |
|---|---|---|
| Fco2 | 1.158 | NAIF DE440s SPK coefficients (0.052 / 0.023) |
| Fe | 1.153 | GRAIL KBR1C range acceleration (0.046 / 0.031) |
| Fh | 1.160 | GRAIL KBR1C range acceleration (0.039 / 0.031) |
