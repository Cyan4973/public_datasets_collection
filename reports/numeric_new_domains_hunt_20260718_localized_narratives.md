# Numeric New Domains Hunt: Google Localized Narratives ADE20K Traces

## Recommendation

Stage `google_localized_narratives_ade20k_traces_f32`, using the fixed public
Google Localized Narratives ADE20K train JSONL annotation file.

## Why This Adds New Territory

- Domain: human multimodal image-annotation behavior.
- Shape: synchronized mouse-trace coordinate/time trajectories recorded while
  annotators narrated image content.
- Difference from accepted datasets: the catalog has image pixels, segmentation
  masks, object bounding boxes, and textual/token streams, but not human
  freehand annotation trajectories tied to narration.
- Numeric representation: normalized trace `x`, trace `y`, and trace time are
  emitted as float32 streams; per-record trace and caption counts are emitted as
  uint32 streams.

## Materiality

The selected object,
`annotations/ade20k_train_localized_narratives.jsonl`, has an observed Google
Cloud Storage size of 802,749,301 bytes. It stays under the 1 GB per-dataset
download cap while providing a large annotation corpus.

The recipe enforces:

- source file floor: 700,000,000 bytes
- source file cap: 900,000,000 bytes
- expected source size: 802,749,301 bytes
- annotation record floor: 10,000 records
- trace-record floor: 8,000 records
- trace-point floor: 2,000,000 points
- primary-byte floor: 32,000,000 bytes
- primary-output hard cap: 1,000,000,000 bytes

## Script To Run

```bash
bash staging/google_localized_narratives_ade20k_traces_f32/download.sh
```

After the download succeeds, build and verify locally:

```bash
bash staging/google_localized_narratives_ade20k_traces_f32/build.sh
bash staging/google_localized_narratives_ade20k_traces_f32/verify.sh
```

## Rejected Candidates In This Pass

- YouTube-8M video/audio embedding shards remained inaccessible with 403
  responses.
- More Open Images segmentation annotations are accessible but too close to
  accepted segmentation and Open Images bounding-box recipes.
- Google Fonts would add typography binaries, but GitHub and Google Fonts
  delivery endpoints are blocked from this environment.

## Acceptance Outcome

The Localized Narratives ADE20K train annotation file downloaded, built, and
verified successfully.

- source bytes: 802,749,301
- JSONL annotation records: 20,476
- records with accepted trace points: 20,476
- trace points: 17,851,358
- primary samples: 5
- primary values: 53,595,026
- primary bytes: 214,380,104
- trace coordinate ranges: x `[0.0, 1.0]`, y `[0.0, 1.0]`
- trace time range: `[0.002, 275.907]`
- max trace points per record: 7,910
- output cap behavior: full fixed JSONL object processed; primary output
  remained below the 1 GB cap
