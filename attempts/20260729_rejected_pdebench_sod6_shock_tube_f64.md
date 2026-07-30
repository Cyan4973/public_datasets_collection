# Rejected: PDEBench Sod6 shock-tube float64 fields

- Dataset ID: `pdebench_sod6_shock_tube_f64`
- Decision: rejected
- Source: PDEBench / SciML PDE Benchmark, DaRUS DOI `10.18419/darus-2986`
- Pinned file: DaRUS file ID `133150`, `Sod6.hdf5`
- Source size: 4,948,776 bytes
- Source SHA-256: `43fe3a129579cd8bd38d5a84502a9f45ed307d8af55fdc631d8fba53998e4d74`
- License: CC BY 4.0, explicitly declared by the dataset record with no additional terms

## Findings

HDF5 1.12.1 `h5dump` confirmed three contiguous, unfiltered native
`H5T_IEEE_F64LE` arrays with shape `(201, 1024)`:

| Dataset | Values observed | Decision |
| --- | --- | --- |
| `/density` | only `1.0` and approximately `1.4` | degenerate two-level initial-condition field |
| `/pressure` | constant `1.0` | reject |
| `/Vx` | constant `0.0` | reject |

The file is therefore not a useful evolving CFD series despite its valid
float64 storage and sufficient nominal element count. Keeping the density
array alone would preserve a trivially repetitive step field and would not
meet the domain-diversity objective in substance.

The next-smallest HDF5 payloads in the same record are the 2D Darcy-flow files
at 1,310,724,488 bytes each. They exceed the recipe's 1 GB output ceiling
before decoding and do not offer a bounded direct subset endpoint. The
reaction-diffusion and Navier--Stokes payloads are larger still (about 4.1 GB
and 9.9 GB per file, respectively).

## Retry condition

Retry PDEBench only if a different version or endpoint exposes a directly
downloadable, non-degenerate native-float64 CFD payload whose complete primary
output remains below 1 GB. Do not download the current multi-gigabyte files in
order to discard most of them locally.
