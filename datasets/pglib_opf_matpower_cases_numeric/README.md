# PGLib-OPF MATPOWER Cases Numeric

This recipe collects public PGLib-OPF power-grid benchmark cases in MATPOWER
case-file format and emits the native numeric matrix blocks used by MATPOWER:
bus, branch, generator, and generator-cost tables.

The material is graph-structured electrical-grid data. Natural samples are
individual matrix blocks from individual power-grid cases, written as raw
little-endian float64 row-major arrays. Small matrix blocks are skipped so the
accepted samples remain materially sized natural records.

## Dataset Shape

- `bus_matrix_f64`: per-bus attributes such as load, voltage, area, and limits.
- `branch_matrix_f64`: per-transmission-line endpoint IDs, impedance, ratings,
  tap settings, status, and angle bounds.
- `gen_matrix_f64`: per-generator output, voltage, limits, and ramp fields.
- `gencost_matrix_f64`: native MATPOWER generator-cost matrices.

All series are parsed directly from `mpc.<field> = [` numeric matrix blocks in
the source `.m` files. The recipe does not synthesize graph topology or remap
identifiers; it preserves source row and column order.

## Usage

```bash
bash staging/pglib_opf_matpower_cases_numeric/download.sh
bash staging/pglib_opf_matpower_cases_numeric/build.sh
bash staging/pglib_opf_matpower_cases_numeric/verify.sh
```

The default download target is the public PGLib-OPF GitHub archive for the
`master` branch. To pin another public archive or branch/tag, set either:

```bash
PGLIB_OPF_ARCHIVE_URL=https://github.com/power-grid-lib/pglib-opf/archive/refs/tags/<tag>.tar.gz
```

or:

```bash
PGLIB_OPF_REF=<branch-or-tag>
```

The build step is local-only and reads from `.data/downloads/` and
`.data/extracted/`.
