# Rejected: Zenodo TrackML event truth float32

- Dataset ID: `zenodo_trackml_event_truth_f32`
- Decision: rejected
- Source: Zenodo record `14386134`, “TrackFormers - Collision Event Data Sets”
- Selected file: `trackml_40k-events-10-to-50-tracks.tar.gz`
- License: CC BY 4.0

## Findings

The selected 134,638,012-byte archive is valid and contains one
1,203,431,441-byte CSV of reduced TrackML/Pythia collision events. A complete
streaming profile found 9,949,945 detector-hit rows grouped into 43,725 event
blocks. The physical columns are:

`x, y, z, vx, vy, vz, px, py, pz, weight`

All values are finite and convert safely to IEEE-754 float32. Integer detector
volume, charge, particle ID, and event ID fields provide grouping and
validation metadata.

The source also repeats complete physical events under different consecutive
event IDs. Exact float32-payload deduplication would retain 19,558 unique events
and remove 24,167 duplicates.

## Why it was rejected

The initial recipe incorrectly interleaved all ten physical fields into one
`[hit, feature]` sample. OpenZL's intended representation separates distinct
fields into homogeneous streams so codecs can model one quantity at a time.

After correct field separation, each event contributes ten separate samples,
one per field. Each such natural sample contains only 55 to 592 values, with a
median of 235. The repository requires a median primary sample size of at least
1,000 values. Concatenating unrelated collision events merely to pass that
floor would violate the natural-record policy.

The family is therefore unsuitable despite its sound license, substantial
aggregate volume, and interesting domain.

## Retry condition

Retry particle-tracking event data only if the source provides naturally larger
events with a median of at least 1,000 hits per individual homogeneous field.
Do not restore the ten-field interleaved representation and do not concatenate
independent events to manufacture larger samples.
