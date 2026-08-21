# UCI Parking Birmingham Occupancy Int16 — 2026-08-21

## Outcome

`uci_parking_birmingham_occupancy_i16` adds 30 complete parking-facility
occupancy timelines containing 35,717 signed-int16 values and 71,434 sample
bytes. Natural samples range from 88 to 1,312 observations, with a median of
1,294, so the family clears the aggregate-value and median-sample acceptance
floors.

This is adjacent to existing bike-rental count series but has a distinct
operational shape: repeatedly sampled bounded inventory state across multiple
parking facilities rather than counts of rental events. The timelines are
stepwise, strongly diurnal, facility-capacity-dependent, and include a small
number of published sensor/reporting anomalies.

## Source and rights

The source is UCI dataset 482, *Parking Birmingham*, donated by Daniel Stolfi,
DOI `10.24432/C51K5Z`. UCI's API describes the underlying Birmingham City
Council/NCP source as UK Open Government Licence. The current official UCI
dataset page explicitly licenses UCI's distribution under CC BY 4.0 and states
that sharing and adaptation are permitted for any purpose.

The recipe pins:

- the 240,539-byte official ZIP archive;
- the 1,479,909-byte `dataset.csv` member;
- the official UCI API metadata; and
- the official UCI rights page.

All four are enforced by exact size and SHA-256. The table contains 35,717
rows spanning 30 source `SystemCodeNumber` values from October through December
2016.

## Natural boundaries and conversion

One complete source facility-code history is one natural sample. Compact codes
and human-readable codes such as `Broad Street`, `Bull Ring`, and `NIA South`
are treated identically; filesystem-safe names are derived separately while
the exact source code remains index metadata.

The CSV's `Occupancy` values are exact decimal integers. Initial assumptions
that they were unsigned proved incorrect: the observed range is `-8..4327`,
including 12 negative readings in `NIA North`. The source also contains 373
readings slightly above their facility's nominal capacity. Both patterns are
preserved exactly as source measurements. Every value fits signed int16 and is
written in canonical little-endian order without scaling, clipping, filling,
or normalization.

Facility ID, capacity, and timestamp fields are used only for validation and
index metadata. They are not emitted as auxiliary or primary sample bytes.
The parser requires stable positive capacity, signed-int16 occupancy,
nondecreasing per-facility time, and nonconstant output.

The source also contains identical repeated observations at some timestamps.
They are retained in source order. A same-timestamp row is accepted only when
its capacity and occupancy agree with the preceding row; conflicting repeats
and backward time fail the recipe.

## Verification

Build and verification passed on 2026-08-21. Verification reparses the exact
pinned CSV, reconstructs all 30 facility timelines, checks signed-int16
little-endian schema and natural boundaries, byte-compares every output, and
requires an exact match between source-derived profiles, the sample index,
ingest statistics, hashes, and sample-directory contents.
