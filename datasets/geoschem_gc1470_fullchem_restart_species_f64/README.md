# GEOS-Chem 14.7.0 fullchem restart: species dry mixing ratios (float64)

Native float64 dry-air mixing ratios (mol mol-1 dry) of the chemical
constituents carried by GEOS-Chem Classic 14.7.0-rc.0 full chemistry, decoded
from the official 4x5-degree, 72-level restart file
`GEOSChem.Restart.fullchem.20190101_0000z.nc4` (MERRA-2 meteorology).

- The Support Team README states that the fullchem restarts were obtained from
  the 14.7.0-rc.0 1-year benchmark.
- The file's own global attributes give `simulation_start_date_and_time`
  2018-12-01 00:00:00z and `simulation_end_date_and_time` 2019-01-01
  00:00:00z. The file is therefore the 2019-01-01 00Z model state at the end
  of a run starting 2018-12-01.

Each sample is one `SpeciesRst_<name>` variable: shape
(time=1, lev=72, lat=46, lon=72) = 238,464 values (1,907,712 bytes), in C order,
little-endian.

**Scope caveat:** every sample comes from **one model timestamp** of **one
simulation**. The diversity is across species, not time. Values run from exact
0 and a numerical floor of about 1e-30 up to 0.823 mol/mol (N2); no value
exceeds 1. The species have very different vertical and horizontal structure:
long-lived halocarbons, short-lived radicals and aerosol tracers. Tracers that
are not constituent mixing ratios are excluded (see below).

## Source and pinning

| item | value |
|---|---|
| object | `https://geos-chem.s3.amazonaws.com/GEOSCHEM_RESTARTS/GC_14.7.0/GEOSChem.Restart.fullchem.20190101_0000z.nc4` |
| size | 589,309,764 bytes |
| S3 ETag | `b0aa35c196ae37c34af5b0478b818072-71` (71 x 8 MiB multipart MD5, recomputed locally) |
| Last-Modified | 2026-02-05T17:27:30Z |
| provenance | `GEOSCHEM_RESTARTS/GC_14.7.0/README` (06 Feb 2026): "The GEOS-Chem Classic "fullchem" restart files ... were obtained from the 1-year benchmark for GEOS-Chem 14.7.0-rc.0." |

The `gcgrid` bucket holds an identical object (same size and ETag). The recipe
uses the `geos-chem` bucket because the AWS registry entry names it
(`ARN: arn:aws:s3:::geos-chem`). The recipe does not use the 20190701 fullchem
file: it would double the output past the 1 GB cap with the same species set.
It also does not use the GCHP cubed-sphere restarts, which are regridded copies.

## Rights

- AWS Open Data Registry entry `datasets/geoschem-input-data.yaml`, quoted
  verbatim: `License: https://geoschem.github.io/license.html`. The same entry
  says the bucket includes "other smaller datasets such as model
  [initial conditions](...)", which covers restart files.
- `https://geoschem.github.io/license.html`, quoted verbatim: "GEOS-Chem,
  including developments, is distributed under the MIT "Expat" public
  license."
- `download.sh` re-fetches both documents on every run and fails if either
  quote is gone.
- Pinned evidence: the registry YAML was last changed in
  awslabs/open-data-registry commit
  `785566b46955a4ef794e9fa411475e3a04a973ff` (2025-02-25). The commit is by
  Bob Yantosca of the GEOS-Chem Support Team ("Removed inversions tag in
  geoschem-input-data.yaml"), so the `License` field comes from the data
  publisher.
- Restart files are GEOS-Chem's own model output: the simulated model state.
  They are not redistributed third-party HEMCO emission inventories or NASA
  meteorological products.
- Caveat for the judge: the license page's wording targets the model code. The
  claim of data coverage rests on the registry's dataset-level `License` field
  for this bucket.
- The README's advice not to use these restarts for production runs without
  spin-up is a scientific caveat, not a usage restriction.

## Decode

The reader is pure standard library: `scripts/h5lite.py`, derived from the
reader in the accepted ICON IVM recipe.

- Superblock v2. The root group uses dense link storage: a fractal heap plus a
  v2 B-tree name index. The reader checks each link's lookup3 name hash, and
  the creation-order index must agree with the name index.
- v2 object headers with continuation blocks. Every lookup3 metadata checksum
  is verified.
- Each species is H5T_IEEE_F64LE, chunked one vertical level per chunk
  (1,1,46,72). Its filter pipeline must be exactly shuffle(8) followed by
  deflate; fletcher32 or any other filter is rejected. The chunk index is a
  v1 B-tree whose 72 chunks must have offsets (0,k,0,0) and zero filter masks.
- Each chunk is inflated to 26,496 bytes and byte-unshuffled, then levels
  0..71 are concatenated.

Outside the samples:
- `Chem_*`, `Met_*`, `AREA` and the coordinate variables are excluded: they
  are other quantities with other units.
- Per-species statistics for all 390 variables (distinct-value count and
  fraction, most common value and its fraction, min, max, zero and negative
  counts) go to `filtered/<id>/species_stats.tsv`. The build log has the same
  figures.

## Semantic exclusions (21 species)

The series is one quantity: constituent dry mixing ratios. A fixed exclusion
list is applied identically in build and verify, before the degeneracy rule.
Each exclusion is recorded with its class and reason (`decision =
excluded_semantic` in `species_stats.tsv`, `excluded_semantic` in
`ingest_stats.json`). Evidence comes from the GEOS-Chem species database at
the matching tag:
`https://raw.githubusercontent.com/geoschem/geos-chem/14.7.0-rc.0/run/shared/species_database.yml`.

- **clock_tracer:** CLOCK. FullName "Clock tracer for diagnosing age of air",
  placeholder MW_g 1.0. Its values run from 122 to 4.42e9: an elapsed-time
  clock, not mol/mol.
- **kpp_prod_loss_tracker:** LBRO2H, LBRO2N, LCH4, LCO, LISOPNO3, LISOPOH,
  LOx, LTRO2H, LTRO2N, LXRO2H, LXRO2N, PCO, PH2O2, POx, PSO4, LNRO2H, LNRO2N.
  Each has FullName "Dummy species to track ...".
- Also **kpp_prod_loss_tracker:** PH2SO4 and PSO4AQ, the SO4-production
  trackers ("SO4 from gas-phase chemistry" / "SO4 from cloud chemistry";
  KPP/fullchem/CHANGELOG_fullchem.md: "Added PH2SO2 and PSO4AQ to track
  production of SO4 for use in TOMAS").
- These trackers hold reaction amounts accumulated for diagnostics, not
  constituent concentrations.
- **proportional_duplicate:** O2. It equals N2 / 3.72696890394 at every
  non-floor cell, so it adds no information beyond N2, which is kept.
  `verify.sh` re-checks that N2/O2 is this constant to within 1e-9 relative.

`verify.sh` also requires each excluded name to exist among the file's 390
`SpeciesRst_*` variables, and to be absent from `samples.jsonl` and from the
sample directory.

## Missing values and degeneracy

- No fill value is defined: the fill-value message carries no value, and there
  are no `_FillValue` or `missing_value` attributes.
- NaN, inf and the netCDF default double fill are fatal.
- Zeros and a numerical floor of about 1e-30 are kept as model state; no
  negative values occur in the kept species. Where a species is chemically
  absent it sits at this floor with jittered mantissas: typically the top 13
  levels (lev indices 59-71) and, for short-lived biogenic intermediates, much
  of the free troposphere. Across the 365 kept samples, the fraction of values
  below 1e-29 is 0 for 102 species, about 0.18 (13/72) for 25, above 0.5 for
  39, and at most 0.79 (EBZ). No kept species holds one exact value across the
  top 13 levels.
- CO2 is a near-constant prescribed field (2.77073674e-4 to 2.77074396e-4,
  181,083 distinct bit patterns). It is kept because it passes the rule.
- Drop rule (applied to the 369 species that are not excluded): a species is
  dropped when one float64 bit pattern covers more
  than 50% of its values, when it has fewer than 1,000 distinct values, or
  when its maximum is below 1e-28 (it never leaves the numerical floor). The
  first two conditions were fixed before the build. The third was added after
  the first build exposed HCFC123, whose jittered floor passed the bit-pattern
  rules.
- **Dropped as degenerate (4):** NAP, NRO2 (81.9% zero, the rest at the
  floor); N (52.8% zero); HCFC123 (max 4.4e-37). The all-zero LNRO2H and
  LNRO2N and the 85.2%-zero PSO4AQ would also fail this rule, but they are
  listed under the semantic exclusions.
- **Kept (365 = 390 - 21 - 4):** 238,464 values each; 87,039,360 values and
  696,314,880 bytes in total.
- Distinct-value fraction 0.236 (H2) to 0.961 (HNO3).
- Most-common-value fraction 0.0003 to 0.342 (O1D, exact zeros).
- Maxima range up to 0.0324 (H2O) and 0.823 (N2); positive minima go down to
  7e-80 (XYLE).
- Per-species min, max and distinct fraction are in
  `filtered/<id>/species_stats.tsv`.

## Novelty

There is no chemical-transport-model trace-species state anywhere in the local
corpus, the registry, the ledger or the downstream corpus. `novelty.py` finds
no matches for the URL or for the terms geos-chem, geoschem, restart, gcgrid.
The nearest families are dynamical and thermodynamic atmospheric fields: the
ClimSim E3SM-MMF f64 state and WeatherBench2 ERA5 f32. These fields differ in
character: log-scale distributions over about 30 decades, with full-mantissa
doubles.

## Scripts

- `download.sh`: checks the license and provenance documents, checks the HEAD
  length and ETag, then runs a resumable curl into a `.part` file. It then
  requires the HDF5 signature and a matching multipart MD5 and logs the
  sha256.
- `build.sh`: runs the synthetic self-test, then `scripts/geoschem_restart.py
  build`.
- `verify.sh`: runs the self-test, then an independent re-decode through the
  creation-order index with its own inflate/unshuffle. It byte-compares each
  sample, recomputes the statistics from the sample files, enforces the
  semantic exclusions, re-applies the drop rule to both kept and dropped
  species, and checks manifest totals.
- The sha256 of the restart file
  (`f13333b8cdc504fca1621ce3021a71d508633fd26e5e073bb14d882dd7d2ab2e`) is
  pinned in `download.sh` and the manifest.
