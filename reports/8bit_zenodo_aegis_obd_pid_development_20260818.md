# AEGIS Automotive OBD PID UInt8 — 2026-08-18

## Outcome

`zenodo_aegis_obd_pid_u8` adds 156 variable-length decoded OBD measurement
timelines from real vehicle trips. The outputs contain 679,651 exact `uint8`
values. Sample lengths range from 1,255 to 11,308 observations, with a median
of 4,140.

This is a new shape for the accepted 8-bit corpus: independently sampled,
variable-length `trip × PID` equipment-telemetry timelines rather than image
planes, dense binary state tracks, fixed-size feature vectors, or categorical
labels.

## Source, license, and safety

The source is Zenodo record 820576, *Automotive Sensor Data. An Example Dataset
from the AEGIS Big Data Project*, DOI `10.5281/zenodo.820576`. The record
declares CC BY 4.0 and describes data collected during 35 trips by one driver
and one vehicle.

The complete archive is pinned at 37,204,969 bytes with MD5
`8c840ca85a0af6cb5784040cb27d465a` and SHA-256
`9a19c404a680462e946abb2b780e43165e04b877f797568b363a1010c8ed2283`.
The required `obdData.csv` member is pinned at 63,583,909 bytes with SHA-256
`089138f38eea82cb085ec858002dd4a29628713f7eaa6d1cd7910a1590e862a5`.

The source archive also contains GPS, accelerometer, and gyroscope tables. The
recipe extracts only `obdData.csv`; emitted bytes exclude coordinates,
timestamps, database row IDs, device metadata, and driver context. Numeric
trip IDs and hexadecimal PID codes are retained only as technical sample-index
labels. The outputs must not be joined back to source location or timestamp
tables to reconstruct routes or driving behavior.

## Discovery and distinction from raw CAN

This family followed a broader attempt to find permissively licensed raw CAN
frame payload bytes. That attempt was blocked: its candidates exposed decoded
signals, JSON V2X messages, derived matrices, or simulated traffic rather than
arbitration-ID-plus-payload frames.

AEGIS is accepted under a separate ID because it is decoded OBD telemetry, not
raw CAN bytes. Its explicit source header is:

`obdData_id,trip_id,obdPid,data,timestamp`

A bounded 32 MiB decoded prefix established the layout on 636,145 rows before
the full 1,196,375-row table was acquired and verified.

## Selection and representation

Rows are grouped by `trip_id` and hexadecimal `obdPid`, preserving source
order. One complete qualifying group is one natural sample. A group is retained
only when:

- it has at least 1,024 observations;
- every published `data` value is numeric, finite, exactly integral, and in
  `0..255`;
- its timestamps are monotonic;
- it is nonconstant; and
- its complete payload is distinct from every other retained sample.

No individual values are dropped. A single blank, nonintegral, negative, or
above-255 value rejects the entire trip/PID group. No rounding, scaling,
clipping, filling, resampling, or cross-group concatenation occurs.

The 156 accepted samples span 27 trip IDs and seven PIDs: calculated engine
load (`04`), coolant temperature (`05`), intake manifold pressure (`0B`),
vehicle speed (`0D`), mass air-flow rate (`10`), barometric pressure (`33`),
and catalyst temperature (`3C`). Source groups for engine RPM, intake-air
temperature, throttle position, and other nonqualifying shapes are excluded
by the same value-domain and diversity rules.

## Verification

Build and verification passed on 2026-08-18. The verifier reparses the complete
CSV and independently reconstructs every selected trip/PID stream, then
byte-compares it with the emitted sample. It also checks type metadata, sample
boundaries, minimum length, nonconstancy, histograms, ranges, unique hashes,
aggregate counts, and the accepted-recipe size floors.
