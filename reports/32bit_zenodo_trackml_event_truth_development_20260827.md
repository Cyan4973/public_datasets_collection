# Zenodo TrackML Event Truth Float32 — 2026-08-27

## Outcome

Accepted `zenodo_trackml_event_truth_f32`: 19,558 unique variable-size
particle-tracking collision events containing 51,052,080 float32 values and
204,208,320 primary bytes.

Each natural sample is one complete event matrix shaped `[detector_hit, 10]`.
Rows preserve measured hit coordinates `x/y/z`, true production vertices
`vx/vy/vz`, true particle momenta `px/py/pz`, and reconstruction weight in
their source order.

## New domain and shape

This is the first accepted within-event particle-tracking family. Existing
particle-physics datasets such as SUSY and MAGIC expose short, independent
feature rows. This source instead contains hundreds of detector hits inside
each collision event, with multiple spatially and kinematically coherent
charged-particle tracks crossing a layered detector.

It also differs from static mesh vertices and geographic point sets: every
sample is a physical event with coupled measured positions, particle origin,
momentum, and hit importance. Unique samples contain 550 to 5,920 values, with
a median of 2,350 values.

## Source and license

Zenodo record `14386134`, “TrackFormers - Collision Event Data Sets,” version
1.0.0, explicitly declares CC BY 4.0. Its description identifies the two
TrackML files as reduced versions of the Pythia-8-simulated TrackML dataset used
for TrackFormers model research.

The recipe selects the bounded
`trackml_40k-events-10-to-50-tracks.tar.gz` artifact. The 134,638,012-byte
archive is pinned by its deposited MD5 and realized SHA-256. Larger files from
the same record exceed the repository source-size cap and are excluded.

## Representation and duplicate handling

The source is decimal CSV rather than typed binary. Each of the ten physical
fields is parsed as a finite number, rounded exactly once to IEEE-754 binary32,
and serialized little-endian in row-major order. Integer detector-volume,
charge, particle-ID, and event-ID columns are retained only for validation and
grouping.

The table contains 9,949,945 hit rows in 43,725 event blocks. It repeats many
complete events under consecutive event IDs; for example, event IDs 0 through
4 have identical physical and identifier rows apart from event ID. Exact
float32 payload deduplication removes 24,167 repeats and retains the first event
ID for each of 19,558 distinct payloads. This prevents replicated examples
from dominating training while preserving every distinct event.

## Verification

Verification pins the record and archive identities, CC BY 4.0 declaration,
tar member inventory, exact CSV schema, event ordering and ID gaps, detector
volume and charge domains, row/event totals, float32 finiteness, duplicate
count, unique sample-size distribution, and aggregate source and retained
payload hashes. It reparses the compressed CSV and compares every emitted
sample, index record, statistics field, and output filename.
