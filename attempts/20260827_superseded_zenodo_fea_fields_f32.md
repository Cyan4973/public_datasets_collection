# Zenodo finite-element fields float32 — superseded

## Outcome

The license-first Zenodo discovery found record `5266382`, “Glacially induced
stresses for a simple ice load,” under CC BY 4.0. Its 79,464,343-byte ZIP is
technically strong and contains six complete stress-tensor components plus one
vertical-displacement field.

It is not a float32 source. Dependency-free inspection of each NetCDF4/HDF5
member found the exact HDF5 `H5T_IEEE_F64LE` datatype descriptor with an
eight-byte element size. Every result dataset is contiguous and shaped
`[161, 4, 120, 120]`.

Narrowing the native values merely to populate the 32-bit corpus would discard
source precision, so the float32 candidate is superseded by the native-width
`zenodo_gia_stress_fields_f64` recipe.

## Retry condition

Do not retry this record as float32. A future float32 finite-element hunt must
identify a different source whose primary result arrays are natively float32 or
are published as decimal text without a wider native binary representation.
