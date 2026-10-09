# GEOS-Chem 14.7.0 fullchem restart species float64 development

## Outcome

Accepted `geoschem_gc1470_fullchem_restart_species_f64` after one repair cycle.

The family holds native float64 dry-air mixing ratios (mol mol-1 dry) of the chemical constituents carried by GEOS-Chem Classic 14.7.0-rc.0 full chemistry on the 4x5-degree, 72-level global grid. Each sample is one species' complete 3-D model-state field from the official restart file. It is the first chemical-transport-model trace-species material in the corpus at any width. It is a new quantity within the gridded atmospheric model-field modality, whose existing families are ClimSim `state_t` f64 and WeatherBench2 ERA5 f32.

Cycle 1 asked for one change: the sample set had to be a single quantity. Three groups were removed by a fixed semantic exclusion list applied before the degeneracy rule:
- the age-of-air `CLOCK` tracer (values 122 to 4.4e9);
- 19 KPP prod/loss tracking species;
- `O2`, which equals N2/3.72696890394 at every non-floor cell.

## Source and rights

- Object: `https://geos-chem.s3.amazonaws.com/GEOSCHEM_RESTARTS/GC_14.7.0/GEOSChem.Restart.fullchem.20190101_0000z.nc4`
- Bytes: 589,309,764
- S3 multipart ETag: `b0aa35c196ae37c34af5b0478b818072-71` (recomputed locally)
- SHA-256: `f13333b8cdc504fca1621ce3021a71d508633fd26e5e073bb14d882dd7d2ab2e`
- Provenance:
  - The GC_14.7.0 README (Support Team, 06 Feb 2026) says the fullchem restarts were obtained from the 14.7.0-rc.0 1-year benchmark.
  - The file's own attributes give a simulation from 2018-12-01 00Z to 2019-01-01 00Z.
- License: MIT (Expat), declared at dataset level by the AWS Open Data Registry entry `geoschem-input-data.yaml`.
  - The entry is ManagedBy the GEOS-Chem Support Team; its last change is commit `785566b46955a4ef794e9fa411475e3a04a973ff`, 2025-02-25.
  - It says `License: https://geoschem.github.io/license.html` for `arn:aws:s3:::geos-chem`, and its Description lists "model initial conditions" as bucket content.
  - The linked page says "GEOS-Chem, including developments, is distributed under the MIT "Expat" public license."
  - Caveat: the page wording targets the model. Coverage of the data rests on the publisher's registry declaration, the same basis used by nine accepted AWS-registry recipes. Restarts are GEOS-Chem's own simulated state, not third-party inventories.
  - `download.sh` re-checks both quotes on every run.

## Shape and conversion

The source is NetCDF-4/HDF5 (superblock v2) with 417 root links in dense storage: 390 `SpeciesRst_*` variables, 10 `Chem_*`, 3 `Met_*`, `AREA` and coordinates.

A pure-stdlib reader decodes each species:
1. Resolve the variable through the fractal heap and v2 B-tree name index (lookup3 hashes and checksums verified).
2. Require `H5T_IEEE_F64LE`, shape (1,72,46,72), chunk (1,1,46,72) and a filter pipeline of exactly shuffle(8)+deflate.
3. Inflate and byte-unshuffle the 72 level chunks and concatenate them in C order (time, lev, lat, lon).
4. Write the stored 8-byte patterns unchanged as little-endian float64.

No fill value is defined. NaN, inf and the netCDF default fill are fatal. Zeros and the jittered ~1e-30 numerical floor (mostly in the 13 levels above the chemistry grid) are kept as model state.

Of the 390 species:
- 21 are excluded semantically (1 `clock_tracer`, 19 `kpp_prod_loss_tracker`, 1 `proportional_duplicate`).
- 4 are dropped under a fixed degeneracy rule (top bit pattern above 50%, fewer than 1,000 distinct values, or max below 1e-28): NAP, NRO2, N and HCFC123.
- Every decision, with its class and reason, is in `filtered/<id>/species_stats.tsv` and `ingest_stats.json`.

## Accepted output

- Species variables decoded: 390
- Excluded semantically: 21
- Dropped as degenerate: 4
- Primary samples: 365
- Values per sample: 238,464 (1,907,712 bytes)
- Primary values: 87,039,360
- Primary bytes: 696,314,880
- Value range:
  - exact 0 and a ~1e-30 floor up to 0.823 (N2); next largest maximum 0.0324 (H2O);
  - positive minima as low as 7e-80 (XYLE);
  - no negative values.
- Distinct-value fraction: 0.236 (H2) to 0.961 (HNO3)
- Most-common-value fraction: 0.0003 to 0.342 (O1D exact zeros)
- Aggregate SHA-256 over the per-sample SHA-256s in index order: `7365816ad68f0e50663072a1c0b9dfbb007a6448a39df974c0b9e45ece68a7ff`
- Measured breadth: OK. Nearest downstream `H2_IpChi2` at feature distance 0.0743 (compression loss 0.0131); own ratio 1.29; mode share 0.0082.

## Judge checks

- **Gate:** `gate.py` PASS with no warnings: 365 samples, 87,039,360 values, 696,314,880 bytes, median 238,464, widths [64].
- **verify.sh**, run by the judge: exit 0 in 26 s. The selftest passed with 12 rejection cases. Then: `verify ok: samples=365 excluded=21 dropped=4 bytes=696314880`.
- **Scripts:** build and verify use only local files. No network calls or credentials in any script. The download log confirms the pinned size, ETag and sha256.
- **Vertical profiles** (stdlib `array` reads) are physically correct:
  - O3: 2.5e-8 at the surface, 6.9e-6 peak at lev 50.
  - CH4: 1.88e-6 falling to 2.6e-7.
  - N2O: 3.30e-7 falling to 2.2e-10.
  - CFC12: 5.0e-10 falling to 1e-12.
  - H2O: 1.05e-2 falling to ~6e-6.
- **Geography and season** are correct:
  - surface ISOP 6.45e-9 over the Amazon against 3.5e-30 over the Pacific;
  - NH3 peaks over India;
  - SALA is higher over ocean;
  - DMS peaks over the January Southern Ocean.
- **Width honesty:** float32-exact fraction 0.0 over 300 random non-zero values in each of the 365 samples.
- **Duplicate scan:** pairwise log-ratio scan of all kept species over 3,000 cells. No proportional copies. The tightest pairs are the near-constant CO2/H2/N2 (sd 0.007-0.011, against ~1e-11 for the excluded O2/N2 pair).
- **Exclusion completeness:** checked against the GEOS-Chem `species_database.yml` at tag 14.7.0-rc.0. Every "Dummy species to track" name present in the file is excluded. Other tracer species in the database (aoa*, e90*, PassiveTracer, stOX, nh_*, st80_25, carbon-mechanism trackers) are absent from this restart. No kept species has a tracer-like FullName or a placeholder MW.
- **Rights:** fetched the registry YAML and the license page and read both directly.
- **Novelty:** `novelty.py` URL and term queries match only this recipe's own staging and ledger rows. Type `sim_atmos_field` matches ClimSim (`state_t` only) and ERA5; no instrument-line or archive matches.
