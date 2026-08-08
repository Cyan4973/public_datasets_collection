# Blocked: Zenodo u-blox NAV-DOP UInt16

- Date: 2026-08-08
- Candidate: `staging/zenodo_ublox_nav_dop_u16`
- Intended domain: GNSS receiver solution-quality telemetry
- Intended primary: native little-endian uint16 GDOP, PDOP, TDOP, VDOP,
  HDOP, NDOP, and EDOP time series from UBX NAV-DOP messages
- Status: blocked before GNSS payload acquisition

## Value

UBX NAV-DOP messages store seven slowly varying dilution-of-precision metrics
as native little-endian `U2` fields. This would differ from the accepted
float64 CORS RINEX carrier-phase and pseudorange observables by representing
receiver solution geometry and quality state.

## Discovery result

A metadata-only Zenodo search used five UBX/u-blox/GNSS queries, examined 69
unique records, required explicit CC0 or CC BY licensing, and rejected human,
smartphone, pedestrian, driver, and vehicle-trajectory contexts.

Results:

- no direct `.ubx` or `.ubx.gz` file survived the license, safety, context,
  and size filters;
- 71 bounded ZIP files survived, but their metadata identified them primarily
  as derived earthquake velocities, RINEX bundles, simulations, or software;
- the two plausible u-blox-named archives from Zenodo record `15789590`
  were inspected using only ZIP tail and central-directory ranges;
- `ubl1074b.zip` contains only `ubl1074b.22o`; and
- `ubl2074b.zip` contains only `ubl2074b.22o`.

The two archives total 83,712,638 bytes, none of which was downloaded as member
payload. The probe fetched 131,114 bytes of ZIP metadata and found zero UBX
members. The `.22o` members are RINEX observation files and do not retain UBX
NAV-DOP messages.

## Evidence

- `.data/discovery/zenodo_ublox_nav_dop_u16/summary.json`
- `.data/discovery/zenodo_ublox_nav_dop_u16/candidates.tsv`
- `.data/discovery/zenodo_ublox_nav_dop_u16/archive_candidates.tsv`
- `.data/discovery/zenodo_ublox_nav_dop_u16/archive_members.tsv`
- `.data/discovery/zenodo_ublox_nav_dop_u16/archive_probe_summary.json`
- `.data/logs/zenodo_ublox_nav_dop_u16/discover.latest.log`
- `.data/logs/zenodo_ublox_nav_dop_u16/probe_archives.latest.log`

## Retry condition

Retry only with an exact, permissively licensed, non-personal source already
known to expose raw `.ubx` or `.ubx.gz` logs containing NAV-DOP messages.
Do not repeat the broad Zenodo search or download generic GNSS/RINEX archives
to look for discarded receiver messages.
