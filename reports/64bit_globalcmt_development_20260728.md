# Global CMT Float64 Development — 2026-07-28

`globalcmt_catalog_f64` adds earthquake source-mechanism inversion results to
the 64-bit corpus. This is distinct from point earthquake catalogs and integer
seismic waveforms: each accepted series is one of the six components of the
centroid moment tensor over catalog events.

The inventory and diversity comparison started from committed
`datasets/*/manifest.toml`, `attempts/dataset_status.tsv`, and
`reports/accepted_recipe_audit.tsv`. Scratch output was used only to validate
this already-grounded candidate.

## Source and URL correction

The initially proposed `globalcmt.org/CMTfiles/jan76_dec20.ndk` URL returned
HTTP 404. The working recipe pins the same January 1976–December 2020 release
at the Global CMT project's canonical Columbia/Lamont-Doherty archive:

`https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/jan76_dec20.ndk`

The user-run download measured:

- source bytes: `23,016,960`
- SHA-256: `baed5ad29a69b57344c6025b27769b1012858aa6b5c807f984696d573c0f0eb4`
- complete five-line NDK events: `56,832`

## Decode and verification

The strict decoder requires complete five-line NDK records. On tensor line
four it requires one shared decimal exponent and six
`(component, standard_error)` pairs. It reconstructs `Mrr`, `Mtt`, `Mpp`,
`Mrt`, `Mrp`, and `Mtp` in dyne-centimeters, preserving catalog order, and
writes one little-endian float64 event series per component. Malformed,
non-finite, or incomplete records fail rather than being skipped.

Independent verification reparses the NDK source and compares every emitted
float64 value in order. Build and verification passed with:

- primary samples: `6`
- primary values: `340,992`
- primary bytes: `2,727,936`
- values per sample / median natural sample: `56,832`
- primary output cap: passed (`< 1 GB`)

The accepted recipe is `datasets/globalcmt_catalog_f64/`.
