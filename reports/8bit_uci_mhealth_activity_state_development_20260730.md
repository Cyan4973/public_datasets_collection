# UCI MHEALTH Activity-State UInt8 Development — 2026-07-30

`uci_mhealth_activity_state_u8` adds long, piecewise-constant human-activity
state timelines to the 8-bit corpus. Existing byte-valued materials include
pixels and rasters, measurement amplitudes, biological symbols and quality
scores, model weights, and sparse clinical event codes. MHEALTH contributes a
different compression regime: very long categorical runs separated by a small
number of real protocol transitions.

The inventory started from committed `datasets/*/manifest.toml`,
`attempts/dataset_status.tsv`, and `reports/accepted_recipe_audit.tsv`. No
corpus decision used `.data/samples/`.

## Source, license, and safety

The source is UCI dataset 319, MHEALTH Dataset, DOI `10.24432/C5TW22`. The
official UCI record identifies its license as CC BY 4.0, permitting training
and commercial reuse with attribution. The archive's README requests citation
of Banos et al., *mHealthDroid: a novel framework for agile development of
mobile health applications* (IWAAL 2014).

The public source archive contains wearable motion, ECG, and magnetic-field
measurements from ten volunteers. This recipe emits none of those sensor
channels and no demographics or identities. It retains only the documented
column-24 activity ID from each pseudonymous subject recording. The manifest
records the human-study provenance and prohibits identity or health inference.

## Natural records and representation

The archive README defines one `mHealth_subjectN.log` file per subject and
documents column 24 as the activity label, with `0` for the null class and
`1..12` for the twelve protocol activities. Each complete subject recording is
therefore one natural primary sample.

The downloader validates the ZIP structure, requires exactly subjects 1
through 10, rejects unsafe paths and oversized members, and checks every
source row for exactly 24 fields and an integral label in `0..12`. Build writes
the final field unchanged as one unsigned byte per observation in source row
order. It does not concatenate subjects, remap activity IDs, retain ZIP bytes,
or use the other 23 fields.

## Realized output

Build and independent verification passed:

- source archive: `75,567,983` bytes
- natural samples: `10` complete subject recordings
- values per sample: `98,304` to `161,280`
- median sample: `120,960` values
- primary values and bytes: `1,215,745`
- observed activity codes: every value `0..12` in every recording
- transitions per recording: `24` to `34`
- longest constant run: `18,022` to `42,701` observations

The aggregate histogram contains `872,550` null-state values and between
`10,342` and `30,720` observations for each activity. Raw DEFLATE level 9
compresses the aggregate `1,215,745` bytes to `2,020` bytes, a ratio of
`0.001662`. This extreme but nonconstant run structure is the intended new
material shape rather than an accidental degenerate field.
