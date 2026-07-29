# NASA Planetary Gravity Harmonics (float64)

Accepted recipe for the NASA PDS GRAIL GRGM1200A degree-1200 lunar Bouguer gravity
model. It emits the decoded dimensionless `Cnm` and `Snm` fields, not text-file
bytes. Each full coefficient field is a meaningful multi-megabyte numerical
model record that can be deterministically sharded by downstream training.

The downloader now pins the exact PDS product validated by the first user run.
`GRAVITY_URL` remains available for an explicitly reviewed replacement:

```bash
GRAVITY_URL=https://official.example/model.gfc.gz \
  bash staging/nasa_pds_gravity_harmonics_f64/download.sh
```

Then run:

```bash
bash staging/nasa_pds_gravity_harmonics_f64/build.sh
bash staging/nasa_pds_gravity_harmonics_f64/verify.sh
```

Plain text, gzip, and ZIP wrappers are supported. Recognized coefficient rows
may be ICGEM `gfc n m C S ...`, PDS `GRCOEF n m C S ...`, or numeric
`n m C S ...` records.

## Realized validation

The user-run download produced an 88,059,844-byte coefficient table with
SHA-256 `3ad34406cbfc22a32d1f9ecad47a12d3449ddb2c848ea62e6049be9472afbf95`.
Local build and verification decoded 721,800 rows through degree/order 1200,
yielding 1,443,600 float64 values and 11,548,800 primary bytes across the Cnm
and Snm model fields.
