# NHTSA FARS 2022 Crash Tables Float64

Candidate recipe for public traffic fatality investigation tables from NHTSA's
Fatality Analysis Reporting System.

The target source is the 2022 national FARS CSV ZIP. Natural samples are one
numeric field from the ACCIDENT, PERSON, or VEHICLE table over preserved source
row order. Identifier-like fields and string fields are excluded.

Run:

```bash
bash staging/nhtsa_fars_2022_crash_tables_f64/download.sh
```

Then build and verify locally:

```bash
bash staging/nhtsa_fars_2022_crash_tables_f64/build.sh
bash staging/nhtsa_fars_2022_crash_tables_f64/verify.sh
```
