# Google Localized Narratives ADE20K Trace Float32

Candidate recipe for Google Localized Narratives ADE20K train annotations.

The target material is human annotation trajectories: synchronized mouse traces
recorded while annotators narrated image regions. Natural samples are homogeneous
numeric streams extracted from one fixed public JSONL annotation file:
normalized trace `x`, normalized trace `y`, trace time, and per-record trace
point counts.

Run:

```bash
bash staging/google_localized_narratives_ade20k_traces_f32/download.sh
```

Then build and verify locally:

```bash
bash staging/google_localized_narratives_ade20k_traces_f32/build.sh
bash staging/google_localized_narratives_ade20k_traces_f32/verify.sh
```
