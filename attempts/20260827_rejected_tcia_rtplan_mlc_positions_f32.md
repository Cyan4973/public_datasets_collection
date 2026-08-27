# Rejected: TCIA RTPLAN MLC positions float32

- Dataset ID: `tcia_rtplan_mlc_positions_f32`
- Date: 2026-08-27
- Status: rejected
- Intended material: radiotherapy multileaf-collimator leaf-bank position
  matrices, separated by bank and written as little-endian float32

## Why it looked useful

DICOM RT Plan objects can contain `MLCX` or `MLCY` leaf positions for every
treatment control point.  A complete leaf bank would form a genuinely new
num32 shape: a control-point by actuator-index matrix with constrained sweeps,
holds, opposing banks, and mechanical position limits.

The intended source was TCIA because its NBIA API exposes stable series
identities and explicit per-series license metadata.  The accepted corpus
already uses TCIA imaging and dose objects, but contains no RTPLAN machine
trajectory family.

## Metadata discovery

An exact query of the CC BY 4.0 `Pancreatic-CT-CBCT-SEG` collection returned
370 series metadata rows but no RTPLAN objects.  Discovery was then broadened
to the official global NBIA `Modality=RTPLAN` endpoint rather than guessing
additional collection names.

The global response contained:

- 484 RTPLAN series from 242 studies;
- explicit CC BY 4.0 metadata for all 484 series;
- only one collection, `Vestibular-Schwannoma-SEG`; and
- only one machine family, Elekta GammaPlan.

## Bounded DICOM probe

The user-run probe downloaded the three largest plans from distinct studies.
Their uncompressed DICOM sizes were 29,876, 28,998, and 28,094 bytes, totaling
86,968 bytes.  Each archive contained one Implicit VR Little Endian RT Plan
Storage object and TCIA's embedded CC BY 4.0 license.

All three objects had the same relevant structure:

- beam-limiting-device types were only `X` and `Y`;
- no `MLCX` or `MLCY` device type occurred;
- every declared Number of Leaf/Jaw Pairs value was zero;
- every Leaf/Jaw Positions field contained exactly two values; and
- the three plans together exposed only 336 jaw-position values across 168
  fields.

These are GammaPlan collimator-jaw apertures, not multileaf-collimator leaf
trajectories.  Their tiny two-value records also cannot provide the proposed
large actuator-matrix shape or meet the natural-sample floor.

## Decision

Reject this source for `tcia_rtplan_mlc_positions_f32`.  Probing more of the
484 live RTPLAN series is unwarranted because they all come from the same
collection and machine family, while the largest representative plans already
demonstrate zero MLC leaf pairs.

Retry the material type only with an exact, permissively licensed source known
to contain linear-accelerator RTPLAN objects with `MLCX` or `MLCY`, substantial
leaf-pair counts, and naturally large control-point trajectories.  Do not
repeat the current TCIA global RTPLAN scan unless its exposed collection or
manufacturer inventory changes.

Ephemeral evidence:

- `.data/logs/tcia_rtplan_mlc_positions_f32/discover.latest.log`
- `.data/logs/tcia_rtplan_mlc_positions_f32/probe.latest.log`
- `.data/discovery/tcia_rtplan_mlc_positions_f32/summary.json`
- `.data/probes/tcia_rtplan_mlc_positions_f32/probe_summary.json`
