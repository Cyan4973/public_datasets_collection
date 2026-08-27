# Zenodo Glacial-Isostatic Stress Fields Float64 — staging

This recipe targets the CC BY 4.0 Zenodo record “Glacially induced stresses
for a simple ice load.” The source contains results from an ABAQUS finite-
element model of glacial isostatic adjustment under a circular ice load.

Seven NetCDF4/HDF5 members provide the six independent components of the
symmetric stress tensor in MPa plus vertical displacement in metres. Every
member contains one contiguous native little-endian float64 array shaped
`[time=161, depth=4, y=120, x=120]`. The axes cover 0–160 ka, depths 2.5–17.5
km, and a 50 km horizontal grid from -2975 to 2975 km in each direction.

Download and preflight from the repository root:

```bash
bash staging/zenodo_gia_stress_fields_f64/download.sh
```

Build and independently verify the samples with:

```bash
bash staging/zenodo_gia_stress_fields_f64/build.sh
bash staging/zenodo_gia_stress_fields_f64/verify.sh
```

The decoder requires only Python’s standard library. It validates the exact
archive and record identities, ZIP member metadata, HDF5 signature, version-2
object header, rank-4 dataspace, exact `H5T_IEEE_F64LE` datatype descriptor,
contiguous layout, payload extent, finite values, zero counts, and output
hashes. The original payload words are copied without numeric conversion.

The result contains six stress-component samples and one displacement sample,
each with 9,273,600 values (74,188,800 bytes), totaling 64,915,200 float64
values and 519,321,600 bytes.
