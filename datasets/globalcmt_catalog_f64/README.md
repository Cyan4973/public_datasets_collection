# Global CMT moment tensors — float64

This recipe decodes the Global Centroid Moment Tensor catalog's standard NDK
records. It emits the six independently inverted tensor components as six
little-endian float64 event series:

- `Mrr`, `Mtt`, `Mpp`
- `Mrt`, `Mrp`, `Mtp`

Each NDK event is a fixed five-line record. Line four contains a shared
base-10 exponent followed by six `(component, standard_error)` pairs. The
recipe reconstructs each component in dyne-centimeters as
`mantissa * 10**exponent`; uncertainty fields remain metadata and are not
included in the primary corpus.

This adds earthquake source-mechanism inversion results, rather than another
hypocenter/magnitude point catalog or seismic waveform.

Project: <https://www.globalcmt.org/>

Official catalog archive:
<https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/>

Pinned release: `jan76_dec20.ndk`, January 1976 through December 2020.

Please cite the Global CMT project and the references requested by its site.

## Run

```bash
bash datasets/globalcmt_catalog_f64/download.sh
bash datasets/globalcmt_catalog_f64/build.sh
bash datasets/globalcmt_catalog_f64/verify.sh
```

The downloader is the only networked step. Build and verification operate on
the local pinned NDK file. Verification reparses that source independently and
compares every emitted float64 value in order.
