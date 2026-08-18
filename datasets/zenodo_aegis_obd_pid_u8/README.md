# AEGIS Automotive OBD PID Timelines UInt8

Exact-source recipe for the decoded OBD observations in
[Zenodo record 820576](https://zenodo.org/records/820576), *Automotive Sensor
Data. An Example Dataset from the AEGIS Big Data Project*.

The CC BY 4.0 source contains data from 35 real trips made by one vehicle. Its
37 MB ZIP archive includes `obdData.csv` alongside GPS, accelerometer, and
gyroscope tables. This family is intentionally distinct from the blocked
raw-CAN-byte search: it evaluates the source's decoded OBD values as natural
per-trip, per-PID timelines.

The bounded discovery helper:

- verifies the exact Zenodo record, license, archive name, size, and checksum;
- range-reads the ZIP directory and at most 8 MiB of the compressed
  `obdData.csv` member;
- checks the inferred five-field layout: row ID, trip ID, hexadecimal OBD PID,
  decoded value, and timestamp;
- profiles each `trip × PID` sequence for length, numeric range, exact
  integrality, distinct-value count, and timestamp ordering;
- marks only nonconstant sequences of at least 1,024 observations whose
  published values are exact integers in `0..255` as provisional `uint8`
  candidates.

No rounding, clipping, scaling, or reinterpretation of CSV text bytes is
allowed. Discovery writes evidence under
`.data/discovery/zenodo_aegis_obd_pid_u8/` and does not download the complete
archive.

Run:

```bash
bash datasets/zenodo_aegis_obd_pid_u8/discover.sh
```

Discovery succeeded on 636,145 bounded-prefix rows, and the complete build
subsequently verified 1,196,375 source observations. It emits 156 natural
samples and 679,651 values across 27 trips and seven qualifying PIDs, with
sample lengths from 1,255 to 11,308 values and a median of 4,140. The source
header explicitly confirms `obdData_id,trip_id,obdPid,data,timestamp`.

To build the complete source:

```bash
bash datasets/zenodo_aegis_obd_pid_u8/download.sh
bash datasets/zenodo_aegis_obd_pid_u8/build.sh
bash datasets/zenodo_aegis_obd_pid_u8/verify.sh
```

`download.sh` is the only acquisition step. It fetches and validates the exact
37,204,969-byte archive, then extracts only `obdData.csv`. Build and verification
are local-only.
