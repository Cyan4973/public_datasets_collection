# davis17_sparse_masks_u8

- Date: 2026-06-01
- Status: needs_tooling
- Candidate dataset: DAVIS 2017 sparse masks
- Source: https://data.vision.ee.ethz.ch/csergi/share/davis/DAVIS-2017-trainval-480p.zip
- Why it looked promising: Annotation masks are native numeric label maps and potentially in-scope.
- Failure class: missing_decoder_tooling
- What happened: The external import depends on PNG mask decoding. This repo does not yet have image-decoding helpers in its stdlib-only recipe set.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Record as tooling-limited instead of adding an ad hoc decoder.
- Retry conditions: Retry after adding a reviewed PNG decode path or approved image tooling.
