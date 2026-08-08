# NASA HEASARC NICER photon PI int16 development — 2026-08-08

## Outcome

Accepted `nasa_heasarc_nicer_pi_i16`: 31 complete native signed-int16
pulse-invariant X-ray energy-channel event sequences from cleaned NASA
NICER/XTI observations.

## Domain and shape distinction

This family contributes irregular X-ray photon-event spectroscopy. It is not
another FITS image: each row represents one detected photon, and the primary
series is its calibrated pulse-invariant detector channel in temporal event
order. The samples are independently decodable, variable-length event
sequences rather than continuous voltage waveforms, raster pixels, or catalog
columns.

The selection covers 19 astronomical target labels, including Cassiopeia A,
3C 273, the Coma cluster, neutron stars, pulsars, magnetars, X-ray binaries,
and commissioning background observations.

## Source selection

Metadata-only discovery traversed official HEASARC June/July 2017 and January
2018 monthly listings. Before payload analysis it pinned the first 36 June
2017 cleaned `_0mpu7_cl.evt.gz` products by lexicographic observation ID.
The exact URLs, sizes, and SHA-256 values are tracked in `sources.tsv`.

- source files: 36
- compressed source bytes: 205,174,726
- selected observations with at least 1,000 events: 31
- excluded tables: three empty, one with 21 events, and one with 389 events

The threshold is a fixed natural-sample size rule. It does not rank targets or
PI values.

## Native type and decoding

Every selected source is a valid gzip-compressed FITS product with
`TELESCOP=NICER`, `INSTRUME=XTI`, and an OGIP `EVENTS` binary table.
The decoder reconstructs all declared column widths and requires them to sum
exactly to `NAXIS1`. The selected PI column has:

- `TFORM=1I`: one signed 16-bit integer per event
- `TSCAL=1`, `TZERO=0`: identity scaling
- `TUNIT=chan`
- `TNULL=-32768`

FITS stores the words big-endian. The recipe changes only byte order to the
collection's canonical little-endian int16 representation.

## Accepted material

- 31 complete observation samples
- 8,938,390 signed-int16 values
- 17,876,780 primary bytes
- 1,114 to 2,472,372 events per observation
- median 18,786 events per observation
- observed range 20 through 1,500
- 8,845,719 adjacent-value transitions
- no null-sentinel or zero values in selected observations
- all complete output hashes unique

Independent verification reparses every FITS source, validates source hashes
and all PI schema properties, regenerates each canonical byte sequence, and
compares every emitted byte and metadata record.

## License and safety

NASA SMD describes its scientific research information as a public trust that
is made publicly available and openly shared. The data come directly from the
official NASA HEASARC mission archive. Preserve NICER, HEASARC, target,
observation-ID, and mission-team attribution.

These are astronomical detector events. They contain no personal, human
subject, or sensitive Earth-observation information.
