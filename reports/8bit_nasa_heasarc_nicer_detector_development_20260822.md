# NASA HEASARC NICER Detector Address Uint8 — 2026-08-22

## Outcome

`nasa_heasarc_nicer_detector_u8` adds three native unsigned-byte event fields
from 31 complete cleaned NICER/XTI observations: detector X address (`RAWX`),
detector Y address (`RAWY`), and hardware detector identifier (`DET_ID`). Each
series contains 8,938,390 values across 31 observation-bounded samples, for 93
samples and 26,815,170 bytes overall. Every series has a median natural sample
of 18,786 events; sample lengths range from 1,114 to 2,472,372 events.

These are categorical detector-routing sequences in photon-arrival order,
distinct from image pixels, audio amplitudes, protocol values, and the
continuous pulse-invariant energy channel already extracted from these files.

## Deliberate source reuse

This recipe does not add independent astronomical observations. It reuses the
exact 36-file June 2017 source selection already pinned by
`nasa_heasarc_nicer_pi_i16` and extracts different native FITS fields. This is
valuable as representation and field-shape diversity, but it must not be
counted as new observational coverage.

To avoid duplicating 205,174,726 compressed bytes locally, the recipe shares
the accepted source inventory and `.data/downloads/nasa_heasarc_nicer_pi_i16/`
cache. Its download step validates every cached source against the tracked
36-row inventory and delegates to the source-owning downloader only if that
cache is absent. The user-run acceptance path reused the cache and made no
network request.

## Source, rights, and selection

The inputs are public NASA HEASARC NICER/XTI cleaned photon-event products,
covered by NASA's open scientific-data policy. Source URLs, observation IDs,
compressed sizes, and SHA-256 identities are inherited from the tracked
inventory whose aggregate hash is pinned in the manifest.

The fixed inventory contains three empty event tables, one 21-event table, and
one 389-event table. As in the PI recipe, those five observations are excluded
by the fixed 1,000-event natural-sample floor, leaving 31 observations.

## Typed FITS decoding

All selected event tables consistently declare:

- `RAWX`: scalar FITS `1B`, identity-scaled, no null, unit `pixel`, observed
  range `0..7`;
- `RAWY`: scalar FITS `1B`, identity-scaled, no null, unit `pixel`, observed
  range `0..6`; and
- `DET_ID`: scalar FITS `1B`, identity-scaled, no null, observed range `0..67`.

The decoder extracts exactly one byte per field from each binary-table row in
source event order. FITS headers, other columns, row framing, and gzip framing
are excluded. No event is dropped, scaled, sorted, padded, split, or joined.
No per-series duplicate samples were found.

## Verification

Build and verification passed on 2026-08-22. Verification revalidates all 36
pinned compressed sources, reparses the FITS event tables, checks all three
field schemas, reconstructs the 93 observation/field samples, byte-compares
them with fresh source extraction, and requires exact agreement among source
profiles, index rows, statistics, hashes, and sample-directory contents.
