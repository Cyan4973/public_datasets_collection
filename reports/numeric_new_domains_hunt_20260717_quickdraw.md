# Numeric New Domains Hunt: Google Quick, Draw! Bitmap Classes

## Historical Recommendation

This recommendation is obsolete. `google_quickdraw_bitmap_classes_u8` was later
retired and rejected because its natural records are individual 28x28 drawings
with 784 uint8 values each; prompt-class bitmap stacks are blind
concatenations.

## Why This Adds New Territory

- Domain: crowdsourced human sketch and doodle raster data.
- Shape: one large uint8 bitmap stack per prompt class, with each drawing represented as a 28x28 grayscale array.
- Difference from accepted datasets: the catalog has digits, fashion images, natural images, medical images, segmentation masks, and object bounding-box annotations, but not crowdsourced freehand sketch rasters.
- Numeric representation: source `uint8` NumPy bitmap payloads are emitted unchanged after stripping the container.

## Materiality

The default six classes are `airplane`, `cat`, `dog`, `car`, `house`, and `tree`. The two checked class files are about 119 MB and 97 MB respectively, so the combined default set should be several hundred MB while staying under the repository's 1 GB per-dataset cap.

The recipe enforces:

- source download hard cap: 1,000,000,000 bytes total
- default total download cap: 900,000,000 bytes
- default per-file download cap: 200,000,000 bytes
- build sample floor: 4 classes
- verify value floor: 400,000,000 uint8 pixel values
- verify primary-byte floor: 400,000,000 bytes
- primary-output hard cap: 1,000,000,000 bytes

## Retired Script

Do not run this recipe. The tracked dataset recipe was removed after rejection.

## Rejected Candidates In This Pass

- BTS TranStats airline on-time data was not retried because earlier repo reports already rejected it without exact verified archive URLs.
- GitHub Archive would have added software event telemetry, but `data.gharchive.org` is blocked from this environment.

## Retirement Outcome

This recipe was later retired and rejected after the natural-record boundary
audit. The accepted output below was a prompt-class stack representation, not an
honest natural-record representation. Each individual Quick, Draw! bitmap
drawing is a 28x28 uint8 image with 784 values, which is below the repository
floor. Prompt-class concatenation is not acceptable.

## Former Acceptance Outcome

The Quick, Draw! bitmap class recipe downloaded, built, and verified successfully.

- source files: 6
- source bytes: 697,673,456
- primary samples: 6
- primary values: 697,672,976
- primary bytes: 697,672,976
- classes: `airplane`, `cat`, `dog`, `car`, `house`, `tree`
- drawings per class:
  - `airplane`: 151,623
  - `cat`: 123,202
  - `dog`: 152,159
  - `car`: 182,764
  - `house`: 135,420
  - `tree`: 144,721
